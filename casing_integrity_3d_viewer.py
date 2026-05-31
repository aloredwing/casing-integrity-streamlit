import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Casing Integrity 3D Viewer", layout="wide")

st.title("Casing Integrity 3D Viewer")
st.caption("Visualizador 3D preliminar para registro caliper de casing")


NULL_VALUES = [-999.25, -999.2500, -999, -999.0]


# =========================================================
# Lectura y limpieza
# =========================================================


def read_uploaded_file(uploaded_file):
    file_name = uploaded_file.name.lower()

    if file_name.endswith(".csv"):
        return pd.read_csv(uploaded_file)

    if file_name.endswith(".xlsx") or file_name.endswith(".xls"):
        return pd.read_excel(uploaded_file)

    raise ValueError("Formato no soportado. Usa CSV, XLSX o XLS.")



def to_numeric_clean(series):
    clean = series.astype(str).str.replace(",", ".", regex=False)
    numeric = pd.to_numeric(clean, errors="coerce")
    numeric = numeric.replace(NULL_VALUES, np.nan)
    return numeric



def normalize_columns(df):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df



def require_columns(df, required_cols):
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        raise ValueError(f"Faltan columnas requeridas: {missing}")


# =========================================================
# Cálculo técnico
# =========================================================


def classify_integrity(integrity_pct):
    if pd.isna(integrity_pct):
        return "Sin dato"
    if integrity_pct >= 80:
        return "Aceptable"
    if integrity_pct >= 60:
        return "Moderado"
    if integrity_pct >= 40:
        return "Crítico"
    return "Severo"



def prepare_casing_log(
    df,
    depth_col,
    id_min_col,
    id_avg_col,
    id_max_col,
    id11_col,
    id12_col,
    nominal_id_col,
    wall_col,
    case_od_manual,
    wall_manual,
    use_file_nominal_values,
):
    required = [depth_col, id_min_col, id_avg_col, id_max_col]
    require_columns(df, required)

    work = pd.DataFrame()
    work["depth_ft"] = to_numeric_clean(df[depth_col])
    work["id_min_in"] = to_numeric_clean(df[id_min_col])
    work["id_avg_in"] = to_numeric_clean(df[id_avg_col])
    work["id_max_in"] = to_numeric_clean(df[id_max_col])

    if id11_col and id11_col in df.columns:
        work["id11_in"] = to_numeric_clean(df[id11_col])
    else:
        work["id11_in"] = work["id_avg_in"]

    if id12_col and id12_col in df.columns:
        work["id12_in"] = to_numeric_clean(df[id12_col])
    else:
        work["id12_in"] = work["id_avg_in"]

    if use_file_nominal_values and nominal_id_col in df.columns and wall_col in df.columns:
        work["nominal_id_in"] = to_numeric_clean(df[nominal_id_col])
        work["nominal_wall_in"] = to_numeric_clean(df[wall_col])
        work["case_od_in"] = work["nominal_id_in"] + 2 * work["nominal_wall_in"]
    else:
        work["case_od_in"] = case_od_manual
        work["nominal_wall_in"] = wall_manual
        work["nominal_id_in"] = case_od_manual - 2 * wall_manual

    work = work.dropna(subset=["depth_ft", "id_avg_in", "id_max_in", "case_od_in", "nominal_wall_in"])
    work = work.sort_values("depth_ft")

    work["remaining_wall_from_idmax_in"] = (work["case_od_in"] - work["id_max_in"]) / 2
    work["remaining_wall_from_idavg_in"] = (work["case_od_in"] - work["id_avg_in"]) / 2
    work["remaining_wall_from_idmin_in"] = (work["case_od_in"] - work["id_min_in"]) / 2

    work["integrity_worst_pct"] = 100 * work["remaining_wall_from_idmax_in"] / work["nominal_wall_in"]
    work["integrity_avg_pct"] = 100 * work["remaining_wall_from_idavg_in"] / work["nominal_wall_in"]
    work["metal_loss_worst_pct"] = 100 - work["integrity_worst_pct"]

    work["id_enlargement_avg_in"] = work["id_avg_in"] - work["nominal_id_in"]
    work["id_enlargement_max_in"] = work["id_max_in"] - work["nominal_id_in"]
    work["ovality_in"] = work["id_max_in"] - work["id_min_in"]
    work["caliper_2arm_delta_in"] = (work["id11_in"] - work["id12_in"]).abs()
    work["class"] = work["integrity_worst_pct"].apply(classify_integrity)

    return work



def critical_intervals(df, threshold_pct):
    data = df.copy().sort_values("depth_ft")
    data["is_critical"] = data["integrity_worst_pct"] < threshold_pct

    intervals = []
    block = []

    for _, row in data.iterrows():
        if row["is_critical"]:
            block.append(row)
        else:
            if block:
                b = pd.DataFrame(block)
                intervals.append(
                    {
                        "from_ft": b["depth_ft"].min(),
                        "to_ft": b["depth_ft"].max(),
                        "min_integrity_pct": b["integrity_worst_pct"].min(),
                        "max_metal_loss_pct": b["metal_loss_worst_pct"].max(),
                        "min_wall_in": b["remaining_wall_from_idmax_in"].min(),
                        "max_id_in": b["id_max_in"].max(),
                        "max_ovality_in": b["ovality_in"].max(),
                    }
                )
                block = []

    if block:
        b = pd.DataFrame(block)
        intervals.append(
            {
                "from_ft": b["depth_ft"].min(),
                "to_ft": b["depth_ft"].max(),
                "min_integrity_pct": b["integrity_worst_pct"].min(),
                "max_metal_loss_pct": b["metal_loss_worst_pct"].max(),
                "min_wall_in": b["remaining_wall_from_idmax_in"].min(),
                "max_id_in": b["id_max_in"].max(),
                "max_ovality_in": b["ovality_in"].max(),
            }
        )

    return pd.DataFrame(intervals)


# =========================================================
# Visualización 3D
# =========================================================


def downsample_by_depth(df, max_points):
    data = df.sort_values("depth_ft").copy()
    if len(data) <= max_points:
        return data

    idx = np.linspace(0, len(data) - 1, max_points).astype(int)
    return data.iloc[idx].copy()



def build_tubular_3d(df, color_col, max_points=1200):
    data = downsample_by_depth(df, max_points)

    theta = np.linspace(0, 2 * np.pi, 80)
    depth = data["depth_ft"].to_numpy(dtype=float)

    radius_x = data["id11_in"].fillna(data["id_avg_in"]).to_numpy(dtype=float) / 2
    radius_y = data["id12_in"].fillna(data["id_avg_in"]).to_numpy(dtype=float) / 2
    color = data[color_col].to_numpy(dtype=float)

    theta_grid, depth_grid = np.meshgrid(theta, depth)
    rx_grid = np.repeat(radius_x.reshape(-1, 1), len(theta), axis=1)
    ry_grid = np.repeat(radius_y.reshape(-1, 1), len(theta), axis=1)
    color_grid = np.repeat(color.reshape(-1, 1), len(theta), axis=1)

    x = rx_grid * np.cos(theta_grid)
    y = ry_grid * np.sin(theta_grid)
    z = depth_grid

    fig = go.Figure(
        data=[
            go.Surface(
                x=x,
                y=y,
                z=z,
                surfacecolor=color_grid,
                colorscale=[
                    [0.00, "red"],
                    [0.40, "orange"],
                    [0.60, "yellow"],
                    [0.80, "lightgreen"],
                    [1.00, "green"],
                ],
                cmin=0,
                cmax=100,
                colorbar=dict(title="Integridad %"),
                hovertemplate=(
                    "MD: %{z:.2f} ft<br>"
                    "Integridad: %{surfacecolor:.1f} %<br>"
                    "X: %{x:.3f} in<br>"
                    "Y: %{y:.3f} in<extra></extra>"
                ),
            )
        ]
    )

    fig.update_layout(
        height=760,
        margin=dict(l=0, r=0, t=20, b=0),
        scene=dict(
            xaxis_title="X, in",
            yaxis_title="Y, in",
            zaxis_title="MD, ft",
            zaxis=dict(autorange="reversed"),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=4),
        ),
    )

    return fig



def build_tracks(df):
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=df["integrity_worst_pct"],
            y=df["depth_ft"],
            mode="lines",
            name="Integridad peor caso, %",
        )
    )

    fig.add_trace(
        go.Scatter(
            x=df["integrity_avg_pct"],
            y=df["depth_ft"],
            mode="lines",
            name="Integridad promedio, %",
        )
    )

    fig.update_layout(
        height=520,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Integridad, %"),
        legend=dict(orientation="h", y=1.05),
        margin=dict(l=20, r=20, t=30, b=20),
    )

    return fig


# =========================================================
# Interfaz
# =========================================================

with st.sidebar:
    st.header("Archivo")
    uploaded = st.file_uploader("Sube tu Excel o CSV", type=["xlsx", "xls", "csv"])

    st.header("Casing")
    st.write("Para tu registro: CASEOD 4.500 in, CASEID 4.052 in, CASETHCK 0.224 in.")
    use_file_nominal_values = st.checkbox("Usar Nominal_ID y Wall_Thickness del archivo", value=True)
    case_od_manual = st.number_input("OD casing, in", min_value=1.0, value=4.500, step=0.001, format="%.3f")
    wall_manual = st.number_input("Wall thickness nominal, in", min_value=0.010, value=0.224, step=0.001, format="%.3f")

    st.header("Criterio")
    threshold = st.slider("Umbral crítico de integridad, %", 10, 100, 60)
    max_points = st.slider("Puntos máximos para 3D", 200, 3000, 1200, step=100)


if uploaded is None:
    st.info("Sube el archivo del registro caliper. El archivo debe tener columnas como Depth, IDMN, IDAV, IDMX, ID11, ID12, Nominal_ID y Wall_Thickness.")
    st.stop()


try:
    raw = normalize_columns(read_uploaded_file(uploaded))
except Exception as exc:
    st.error(f"No pude leer el archivo: {exc}")
    st.stop()


st.subheader("Vista previa del archivo")
st.dataframe(raw.head(25), use_container_width=True)

cols = list(raw.columns)

st.subheader("Mapeo de columnas")
col1, col2, col3, col4 = st.columns(4)

with col1:
    depth_col = st.selectbox("Profundidad", cols, index=cols.index("Depth") if "Depth" in cols else 0)
    id_min_col = st.selectbox("ID mínimo", cols, index=cols.index("IDMN") if "IDMN" in cols else 0)

with col2:
    id_avg_col = st.selectbox("ID promedio", cols, index=cols.index("IDAV") if "IDAV" in cols else 0)
    id_max_col = st.selectbox("ID máximo", cols, index=cols.index("IDMX") if "IDMX" in cols else 0)

with col3:
    id11_options = [None] + cols
    id12_options = [None] + cols
    id11_col = st.selectbox("Diámetro 11", id11_options, index=id11_options.index("ID11") if "ID11" in cols else 0)
    id12_col = st.selectbox("Diámetro 12", id12_options, index=id12_options.index("ID12") if "ID12" in cols else 0)

with col4:
    nominal_id_col = st.selectbox("ID nominal", cols, index=cols.index("Nominal_ID") if "Nominal_ID" in cols else 0)
    wall_col = st.selectbox("Espesor nominal", cols, index=cols.index("Wall_Thickness") if "Wall_Thickness" in cols else 0)


try:
    log = prepare_casing_log(
        raw,
        depth_col=depth_col,
        id_min_col=id_min_col,
        id_avg_col=id_avg_col,
        id_max_col=id_max_col,
        id11_col=id11_col,
        id12_col=id12_col,
        nominal_id_col=nominal_id_col,
        wall_col=wall_col,
        case_od_manual=case_od_manual,
        wall_manual=wall_manual,
        use_file_nominal_values=use_file_nominal_values,
    )
except Exception as exc:
    st.error(f"Error al preparar datos: {exc}")
    st.stop()

if log.empty:
    st.error("No quedaron registros válidos después de limpiar los valores nulos.")
    st.stop()


st.subheader("Filtro de profundidad")
min_depth = float(log["depth_ft"].min())
max_depth = float(log["depth_ft"].max())
selected_depth = st.slider("Rango MD, ft", min_depth, max_depth, (min_depth, max_depth))
filtered = log[(log["depth_ft"] >= selected_depth[0]) & (log["depth_ft"] <= selected_depth[1])].copy()

if filtered.empty:
    st.warning("No hay datos en el intervalo seleccionado.")
    st.stop()


k1, k2, k3, k4, k5 = st.columns(5)
k1.metric("MD inicial", f"{filtered['depth_ft'].min():.2f} ft")
k2.metric("MD final", f"{filtered['depth_ft'].max():.2f} ft")
k3.metric("Integridad mínima", f"{filtered['integrity_worst_pct'].min():.1f} %")
k4.metric("Espesor mínimo", f"{filtered['remaining_wall_from_idmax_in'].min():.3f} in")
k5.metric("Pérdida máxima", f"{filtered['metal_loss_worst_pct'].max():.1f} %")


st.subheader("Tubular 3D aproximado")
st.write("El color usa la integridad de peor caso calculada con IDMX. La geometría usa ID11 e ID12 como elipse aproximada del diámetro interno.")
fig3d = build_tubular_3d(filtered, color_col="integrity_worst_pct", max_points=max_points)
st.plotly_chart(fig3d, use_container_width=True)


st.subheader("Tracks de integridad")
st.plotly_chart(build_tracks(filtered), use_container_width=True)


st.subheader("Intervalos críticos")
intervals = critical_intervals(filtered, threshold)
if intervals.empty:
    st.success("No se detectan intervalos por debajo del umbral seleccionado.")
else:
    st.dataframe(intervals.round(3), use_container_width=True)


st.subheader("Tabla procesada")
show_cols = [
    "depth_ft",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "id11_in",
    "id12_in",
    "nominal_id_in",
    "nominal_wall_in",
    "case_od_in",
    "remaining_wall_from_idmax_in",
    "integrity_worst_pct",
    "metal_loss_worst_pct",
    "ovality_in",
    "class",
]
st.dataframe(filtered[show_cols].round(4), use_container_width=True)

csv = filtered[show_cols].to_csv(index=False).encode("utf-8")
st.download_button(
    "Descargar tabla procesada CSV",
    data=csv,
    file_name="casing_integrity_processed.csv",
    mime="text/csv",
)

if not intervals.empty:
    csv_intervals = intervals.to_csv(index=False).encode("utf-8")
    st.download_button(
        "Descargar intervalos críticos CSV",
        data=csv_intervals,
        file_name="casing_integrity_critical_intervals.csv",
        mime="text/csv",
    )
