import re
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Casing Integrity 3D Viewer", layout="wide")

st.title("Casing Integrity 3D Viewer")
st.caption(
    "Sube un archivo LAS, Excel o CSV del registro caliper. "
    "La app diferencia picos puntuales de problemas sostenidos del casing."
)


NULL_VALUES = [-999.25, -999.2500, -999, -999.0]


RANGOS_PROBLEMA = pd.DataFrame(
    [
        {"Clase": "Bajo", "Rango": "0 a < 35 %", "Interpretación": "Sin anomalía sostenida relevante"},
        {"Clase": "Moderado", "Rango": "35 a < 60 %", "Interpretación": "Revisar tendencia o intervalo"},
        {"Clase": "Crítico", "Rango": "60 a < 80 %", "Interpretación": "Posible problema sostenido"},
        {"Clase": "Severo", "Rango": "80 a 100 %", "Interpretación": "Alta probabilidad de restricción, deformación o daño sostenido"},
    ]
)


def parse_float(texto, default=None):
    if texto is None:
        return default

    texto = str(texto).replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", texto)

    if match:
        return float(match.group(0))

    return default


def limpiar_numero(serie):
    return pd.to_numeric(
        serie.astype(str).str.replace(",", ".", regex=False),
        errors="coerce"
    ).replace(NULL_VALUES, np.nan)


def buscar_columna(columnas, opciones):
    columnas_limpias = {str(c).strip().upper(): c for c in columnas}

    for opcion in opciones:
        if opcion.upper() in columnas_limpias:
            return columnas_limpias[opcion.upper()]

    return None


def clasificar_problema(score):
    if score >= 80:
        return "Severo"
    if score >= 60:
        return "Crítico"
    if score >= 35:
        return "Moderado"

    return "Bajo"


def clasificar_integridad(integridad):
    if integridad >= 80:
        return "Aceptable"
    if integridad >= 60:
        return "Moderado"
    if integridad >= 40:
        return "Crítico"

    return "Severo"


def leer_las_desde_texto(texto):
    lineas = texto.splitlines()

    parametros = {}
    curvas = []
    dentro_curvas = False

    for linea in lineas:
        limpia = linea.strip()

        if limpia.startswith("~"):
            dentro_curvas = limpia.upper().startswith("~CURVE")
            continue

        if dentro_curvas:
            match = re.match(r"\s*([A-Za-z0-9_]+)\.", linea)
            if match:
                curvas.append(match.group(1).strip())

        if "." in linea and ":" in linea:
            izquierda = linea.split(":", 1)[0]
            match = re.match(r"\s*([A-Za-z0-9_]+)\.[^\s]*\s*(.*)$", izquierda)
            if match:
                parametros[match.group(1).upper()] = match.group(2).strip()

    indice_a = None

    for i, linea in enumerate(lineas):
        if linea.strip().upper().startswith("~A"):
            indice_a = i
            partes_a = linea.split()

            if len(partes_a) > 1:
                curvas_a = partes_a[1:]

                if len(curvas_a) >= len(curvas):
                    curvas = curvas_a

            break

    if indice_a is None:
        raise ValueError("No se encontró la sección ~A del archivo LAS.")

    if not curvas:
        raise ValueError("No se encontraron curvas en el archivo LAS.")

    filas = []

    for linea in lineas[indice_a + 1:]:
        limpia = linea.strip()

        if not limpia or limpia.startswith("~") or limpia.startswith("#"):
            continue

        partes = limpia.split()

        if len(partes) < len(curvas):
            continue

        try:
            valores = [float(x.replace(",", ".")) for x in partes[:len(curvas)]]
            filas.append(valores)
        except ValueError:
            continue

    if not filas:
        raise ValueError("No se encontraron datos numéricos en el LAS.")

    df = pd.DataFrame(filas, columns=curvas)
    df = df.replace(NULL_VALUES, np.nan)

    case_od = parse_float(parametros.get("CASEOD"), 5.500)
    case_id = parse_float(parametros.get("CASEID"), None)
    case_thick = parse_float(parametros.get("CASETHCK"), 0.275)

    if case_id is None:
        case_id = case_od - 2 * case_thick

    meta = {
        "pozo": parametros.get("WELL", ""),
        "campo": parametros.get("FLD", ""),
        "compania": parametros.get("COMP", ""),
        "case_od": case_od,
        "case_id": case_id,
        "case_thick": case_thick,
        "fuente": "LAS"
    }

    return df, meta


def leer_archivo(archivo):
    nombre = archivo.name.lower()

    if nombre.endswith(".las"):
        texto = archivo.getvalue().decode("utf-8", errors="ignore")
        return leer_las_desde_texto(texto)

    if nombre.endswith(".xlsx") or nombre.endswith(".xls"):
        datos = archivo.getvalue()

        excel_texto = pd.read_excel(BytesIO(datos), header=None, dtype=str)
        celdas = []

        for col in excel_texto.columns:
            celdas.extend(excel_texto[col].dropna().astype(str).tolist())

        texto_unido = "\n".join(celdas)

        if (
            "~Version" in texto_unido
            or "~VERSION" in texto_unido
            or "~Curve" in texto_unido
            or "~CURVE" in texto_unido
            or "~A" in texto_unido
        ):
            return leer_las_desde_texto(texto_unido)

        df = pd.read_excel(BytesIO(datos))

        meta = {
            "pozo": "",
            "campo": "",
            "compania": "",
            "case_od": 5.500,
            "case_id": 4.950,
            "case_thick": 0.275,
            "fuente": "Excel tabular"
        }

        return df, meta

    if nombre.endswith(".csv"):
        df = pd.read_csv(archivo)

        meta = {
            "pozo": "",
            "campo": "",
            "compania": "",
            "case_od": 5.500,
            "case_id": 4.950,
            "case_thick": 0.275,
            "fuente": "CSV"
        }

        return df, meta

    raise ValueError("Formato no soportado. Usa LAS, Excel o CSV.")


def ventana_puntos_por_ft(depth, ventana_ft):
    d = pd.Series(depth).dropna().sort_values().to_numpy()

    if len(d) < 3:
        return 5

    paso = np.nanmedian(np.diff(d))

    if not np.isfinite(paso) or paso <= 0:
        paso = 0.125

    puntos = int(round(float(ventana_ft) / paso))
    puntos = max(5, puntos)

    if puntos % 2 == 0:
        puntos += 1

    return puntos


def suavizar_sostenido(serie, ventana_puntos):
    return (
        pd.Series(serie)
        .rolling(window=ventana_puntos, center=True, min_periods=max(3, ventana_puntos // 3))
        .median()
        .bfill()
        .ffill()
        .to_numpy()
    )


def crear_motivo(row):
    motivos = []

    if row["wear_score_sustained_pct"] >= 35:
        motivos.append("aumento sostenido de IDMX o desgaste")

    if row["restriction_score_sustained_pct"] >= 35:
        motivos.append("reducción sostenida de IDMN o posible restricción")

    if row["ovality_score_sustained_pct"] >= 35:
        motivos.append("ovalidad sostenida")

    if row["eccentricity_score_sustained_pct"] >= 35:
        motivos.append("excentricidad sostenida")

    if row["jump_score_sustained_pct"] >= 35:
        motivos.append("cambio brusco sostenido")

    if row["spike_score_pct"] >= 60 and row["problem_score_pct"] < 35:
        motivos.append("pico puntual de lectura, revisar como posible ruido, collar, suciedad o centralización")

    if not motivos:
        return "sin anomalía sostenida relevante"

    return ", ".join(motivos)


def tipo_alerta(row):
    if row["problem_score_pct"] >= 60:
        return "Problema sostenido"
    if row["problem_score_pct"] >= 35:
        return "Tendencia moderada"
    if row["spike_score_pct"] >= 60:
        return "Pico puntual"

    return "Normal"


def procesar_datos(
    df,
    col_depth,
    col_idmn,
    col_idav,
    col_idmx,
    case_od,
    nominal_id,
    wall_thickness,
    restriction_ref,
    ovality_ref,
    eccentricity_ref,
    jump_ref,
    ventana_sostenida_ft
):
    data = pd.DataFrame()

    data["depth_ft"] = limpiar_numero(df[col_depth])
    data["id_min_in"] = limpiar_numero(df[col_idmn])
    data["id_avg_in"] = limpiar_numero(df[col_idav])
    data["id_max_in"] = limpiar_numero(df[col_idmx])

    data["case_od_in"] = case_od
    data["nominal_id_in"] = nominal_id
    data["nominal_wall_in"] = wall_thickness

    col_ecc = buscar_columna(df.columns, ["ECCE", "ECC", "ECCENTERING"])
    col_oval_las = buscar_columna(df.columns, ["OVAL", "OVALITY"])

    if col_ecc:
        data["eccentricity_in"] = limpiar_numero(df[col_ecc])
    else:
        data["eccentricity_in"] = np.nan

    if col_oval_las:
        data["ovality_las_in"] = limpiar_numero(df[col_oval_las])
    else:
        data["ovality_las_in"] = np.nan

    id_arm_cols = []

    for i in range(1, 25):
        nombre = f"ID{i:02d}"
        col = buscar_columna(df.columns, [nombre, f"ID{i}"])

        if col:
            nuevo = f"id{i:02d}_in"
            data[nuevo] = limpiar_numero(df[col])
            id_arm_cols.append(nuevo)

    data = data.dropna(subset=["depth_ft", "id_min_in", "id_avg_in", "id_max_in"])
    data = data.sort_values("depth_ft").reset_index(drop=True)

    data["remaining_wall_raw_in"] = (data["case_od_in"] - data["id_max_in"]) / 2
    data["remaining_wall_in"] = data["remaining_wall_raw_in"].clip(lower=0)

    data["integrity_raw_pct"] = 100 * data["remaining_wall_raw_in"] / data["nominal_wall_in"]
    data["integrity_pct"] = data["integrity_raw_pct"].clip(lower=0, upper=100)

    data["metal_loss_pct"] = 100 - data["integrity_pct"]
    data["metal_loss_pct"] = data["metal_loss_pct"].clip(lower=0, upper=100)

    data["id_enlargement_max_in"] = data["id_max_in"] - data["nominal_id_in"]
    data["id_restriction_min_in"] = data["nominal_id_in"] - data["id_min_in"]

    data["diameter_spread_in"] = data["id_max_in"] - data["id_min_in"]
    data["ovality_calc_in"] = data["diameter_spread_in"].clip(lower=0)

    data["wear_score_raw_pct"] = np.clip(
        (data["id_enlargement_max_in"].clip(lower=0) / max(2 * wall_thickness, 0.001)) * 100,
        0,
        100
    )

    data["restriction_score_raw_pct"] = np.clip(
        (data["id_restriction_min_in"].clip(lower=0) / max(restriction_ref, 0.001)) * 100,
        0,
        100
    )

    data["ovality_score_raw_pct"] = np.clip(
        (data["ovality_calc_in"].clip(lower=0) / max(ovality_ref, 0.001)) * 100,
        0,
        100
    )

    data["eccentricity_score_raw_pct"] = np.clip(
        (data["eccentricity_in"].fillna(0).clip(lower=0) / max(eccentricity_ref, 0.001)) * 100,
        0,
        100
    )

    salto_idmn = data["id_min_in"].diff().abs().fillna(0)
    salto_idmx = data["id_max_in"].diff().abs().fillna(0)

    data["jump_score_raw_pct"] = np.clip(
        (np.maximum(salto_idmn, salto_idmx) / max(jump_ref, 0.001)) * 100,
        0,
        100
    )

    ventana_puntos = ventana_puntos_por_ft(data["depth_ft"], ventana_sostenida_ft)

    for base in ["wear", "restriction", "ovality", "eccentricity", "jump"]:
        data[f"{base}_score_sustained_pct"] = suavizar_sostenido(
            data[f"{base}_score_raw_pct"],
            ventana_puntos
        )

    data["spike_score_pct"] = data[
        [
            "wear_score_raw_pct",
            "restriction_score_raw_pct",
            "ovality_score_raw_pct",
            "eccentricity_score_raw_pct",
            "jump_score_raw_pct"
        ]
    ].max(axis=1)

    data["problem_score_pct"] = data[
        [
            "wear_score_sustained_pct",
            "restriction_score_sustained_pct",
            "ovality_score_sustained_pct",
            "eccentricity_score_sustained_pct",
            "jump_score_sustained_pct"
        ]
    ].max(axis=1)

    data["out_of_physical_range"] = data["id_max_in"] > data["case_od_in"]
    data["integrity_class"] = data["integrity_pct"].apply(clasificar_integridad)
    data["problem_class"] = data["problem_score_pct"].apply(clasificar_problema)
    data["alert_type"] = data.apply(tipo_alerta, axis=1)
    data["probable_cause"] = data.apply(crear_motivo, axis=1)
    data["smoothing_window_points"] = ventana_puntos

    return data, id_arm_cols


def textos_hover(data):
    textos = []

    for _, row in data.iterrows():
        texto = (
            f"<b>Lectura del casing</b><br>"
            f"MD: {row['depth_ft']:.2f} ft<br>"
            f"Tipo de alerta: {row['alert_type']}<br>"
            f"Problema sostenido: {row['problem_score_pct']:.1f} %<br>"
            f"Pico puntual: {row['spike_score_pct']:.1f} %<br>"
            f"Clasificación: {row['problem_class']}<br>"
            f"Desgaste por IDMX: {row['metal_loss_pct']:.1f} %<br>"
            f"Integridad: {row['integrity_pct']:.1f} %<br>"
            f"Espesor remanente: {row['remaining_wall_in']:.3f} in<br>"
            f"IDMN: {row['id_min_in']:.3f} in<br>"
            f"IDAV: {row['id_avg_in']:.3f} in<br>"
            f"IDMX: {row['id_max_in']:.3f} in<br>"
            f"Restricción IDMN: {row['id_restriction_min_in']:.3f} in<br>"
            f"Ovalidad calculada: {row['ovality_calc_in']:.3f} in<br>"
            f"Excentricidad: {row['eccentricity_in']:.3f} in<br>"
            f"Motivo probable: {row['probable_cause']}"
        )

        textos.append(texto)

    return textos


def construir_superficie(data, id_arm_cols):
    if len(id_arm_cols) >= 6:
        ids = data[id_arm_cols].copy()

        for col in id_arm_cols:
            ids[col] = ids[col].fillna(data["id_avg_in"])

        radios = ids.to_numpy(dtype=float) / 2
        radios = np.clip(radios, 0, data["case_od_in"].to_numpy().reshape(-1, 1) / 2)

        theta = np.linspace(0, 2 * np.pi, len(id_arm_cols), endpoint=False)

        radios = np.column_stack([radios, radios[:, 0]])
        theta = np.append(theta, 2 * np.pi)
    else:
        theta = np.linspace(0, 2 * np.pi, 72)

        rx = data["id_max_in"].fillna(data["id_avg_in"]).to_numpy() / 2
        ry = data["id_min_in"].fillna(data["id_avg_in"]).to_numpy() / 2

        rx = np.clip(rx, 0, data["case_od_in"].to_numpy() / 2)
        ry = np.clip(ry, 0, data["case_od_in"].to_numpy() / 2)

        radios = []

        for i in range(len(data)):
            denominador = np.sqrt(
                (ry[i] * np.cos(theta)) ** 2 +
                (rx[i] * np.sin(theta)) ** 2
            )

            denominador = np.where(denominador == 0, 1e-9, denominador)
            r = (rx[i] * ry[i]) / denominador
            radios.append(r)

        radios = np.array(radios)

    depth = data["depth_ft"].to_numpy()
    theta_grid, depth_grid = np.meshgrid(theta, depth)

    x = radios * np.cos(theta_grid)
    y = radios * np.sin(theta_grid)
    z = depth_grid

    return x, y, z


def grafico_3d(data, id_arm_cols, max_points, umbral_problema):
    if len(data) > max_points:
        indices = np.linspace(0, len(data) - 1, max_points).astype(int)
        data_plot = data.iloc[indices].copy()
    else:
        data_plot = data.copy()

    x, y, z = construir_superficie(data_plot, id_arm_cols)

    score = data_plot["problem_score_pct"].fillna(0).to_numpy()
    score_grid = np.repeat(score.reshape(-1, 1), x.shape[1], axis=1)

    textos = textos_hover(data_plot)
    hover_grid = np.repeat(np.array(textos, dtype=object).reshape(-1, 1), x.shape[1], axis=1)

    fig = go.Figure()

    fig.add_trace(
        go.Surface(
            x=x,
            y=y,
            z=z,
            surfacecolor=score_grid,
            text=hover_grid,
            cmin=0,
            cmax=100,
            colorscale=[
                [0.00, "green"],
                [0.35, "lightgreen"],
                [0.60, "yellow"],
                [0.80, "orange"],
                [1.00, "red"],
            ],
            colorbar=dict(
                title="Problema sostenido %",
                tickvals=[17.5, 47.5, 70, 90],
                ticktext=["Bajo", "Moderado", "Crítico", "Severo"]
            ),
            hovertemplate="%{text}<extra></extra>",
            hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
            name="Casing"
        )
    )

    fig.add_trace(
        go.Scatter3d(
            x=np.zeros(len(data_plot)),
            y=np.zeros(len(data_plot)),
            z=data_plot["depth_ft"],
            mode="lines+markers",
            line=dict(width=7, color="black"),
            marker=dict(size=4, color="black"),
            text=textos,
            hovertemplate="%{text}<extra></extra>",
            hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
            name="Línea de lectura"
        )
    )

    crit = data_plot[data_plot["problem_score_pct"] >= umbral_problema].copy()

    if not crit.empty:
        if len(crit) > 120:
            crit = crit.sort_values("problem_score_pct", ascending=False).head(120)
            crit = crit.sort_values("depth_ft")

        r_lateral = np.nanmax(np.sqrt(x ** 2 + y ** 2)) + 0.35

        fig.add_trace(
            go.Scatter3d(
                x=np.ones(len(crit)) * r_lateral,
                y=np.zeros(len(crit)),
                z=crit["depth_ft"],
                mode="markers",
                marker=dict(
                    size=5,
                    color=crit["problem_score_pct"],
                    colorscale="Turbo",
                    cmin=0,
                    cmax=100,
                    symbol="diamond"
                ),
                text=textos_hover(crit),
                hovertemplate="%{text}<extra></extra>",
                hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
                name="Alertas sostenidas"
            )
        )

    fig.add_annotation(
        text=(
            "<b>Rangos:</b> Bajo &lt;35% | Moderado 35-59% | "
            "Crítico 60-79% | Severo ≥80%"
        ),
        xref="paper",
        yref="paper",
        x=0.01,
        y=1.05,
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.85)",
        bordercolor="gray",
        borderwidth=1
    )

    fig.update_layout(
        height=760,
        scene=dict(
            xaxis_title="X, in",
            yaxis_title="Y, in",
            zaxis_title="MD, ft",
            zaxis=dict(autorange="reversed"),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=4),
        ),
        margin=dict(l=0, r=0, t=60, b=0),
        legend=dict(orientation="h")
    )

    return fig


def grafico_tracks(data, umbral_problema):
    fig = go.Figure()

    curvas = [
        ("problem_score_pct", "Problema sostenido, %"),
        ("spike_score_pct", "Pico puntual, %"),
        ("metal_loss_pct", "Desgaste por IDMX, %"),
        ("restriction_score_sustained_pct", "Restricción IDMN sostenida, %"),
        ("ovality_score_sustained_pct", "Ovalidad sostenida, %"),
        ("eccentricity_score_sustained_pct", "Excentricidad sostenida, %"),
        ("integrity_pct", "Integridad, %"),
    ]

    for col, nombre in curvas:
        fig.add_trace(
            go.Scatter(
                x=data[col],
                y=data["depth_ft"],
                mode="lines",
                name=nombre
            )
        )

    fig.add_vline(
        x=umbral_problema,
        line_dash="dash",
        annotation_text="Umbral problema"
    )

    fig.update_layout(
        height=580,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Score / porcentaje, %", range=[0, 100]),
        legend=dict(orientation="h"),
        margin=dict(l=20, r=20, t=50, b=20),
    )

    return fig


def grafico_id(data):
    fig = go.Figure()

    for col, nombre in [
        ("id_min_in", "IDMN"),
        ("id_avg_in", "IDAV"),
        ("id_max_in", "IDMX"),
    ]:
        fig.add_trace(
            go.Scatter(
                x=data[col],
                y=data["depth_ft"],
                mode="lines",
                name=nombre
            )
        )

    nominal = float(data["nominal_id_in"].iloc[0])
    od = float(data["case_od_in"].iloc[0])

    fig.add_vline(x=nominal, line_dash="dash", annotation_text="ID nominal")
    fig.add_vline(x=od, line_dash="dot", annotation_text="OD casing")

    fig.update_layout(
        height=560,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Diámetro interno, in"),
        legend=dict(orientation="h"),
        margin=dict(l=20, r=20, t=50, b=20),
    )

    return fig


def crear_intervalo(b):
    fila_max = b.sort_values("problem_score_pct", ascending=False).iloc[0]

    return {
        "from_ft": b["depth_ft"].min(),
        "to_ft": b["depth_ft"].max(),
        "longitud_ft": b["depth_ft"].max() - b["depth_ft"].min(),
        "max_problem_score_pct": b["problem_score_pct"].max(),
        "max_spike_score_pct": b["spike_score_pct"].max(),
        "max_metal_loss_pct": b["metal_loss_pct"].max(),
        "max_restriction_score_pct": b["restriction_score_sustained_pct"].max(),
        "max_ovality_score_pct": b["ovality_score_sustained_pct"].max(),
        "max_eccentricity_score_pct": b["eccentricity_score_sustained_pct"].max(),
        "min_integrity_pct": b["integrity_pct"].min(),
        "min_idmn_in": b["id_min_in"].min(),
        "max_idmx_in": b["id_max_in"].max(),
        "probable_cause": fila_max["probable_cause"],
        "class": clasificar_problema(b["problem_score_pct"].max())
    }


def intervalos_criticos(data, umbral):
    data = data.sort_values("depth_ft").copy()
    data["critico"] = data["problem_score_pct"] >= umbral

    intervalos = []
    bloque = []

    for _, row in data.iterrows():
        if row["critico"]:
            bloque.append(row)
        else:
            if bloque:
                b = pd.DataFrame(bloque)
                intervalos.append(crear_intervalo(b))
                bloque = []

    if bloque:
        b = pd.DataFrame(bloque)
        intervalos.append(crear_intervalo(b))

    return pd.DataFrame(intervalos)


with st.sidebar:
    st.header("Archivo")

    archivo = st.file_uploader(
        "Sube tu archivo LAS, Excel o CSV",
        type=["las", "xlsx", "xls", "csv"]
    )


if archivo is None:
    st.info("Sube tu archivo LAS, Excel o CSV para empezar.")
    st.stop()


try:
    df, meta = leer_archivo(archivo)
except Exception as e:
    st.error(f"No pude leer el archivo: {e}")
    st.stop()


st.sidebar.header("Datos del casing")

case_od = st.sidebar.number_input(
    "OD casing, in",
    value=float(meta["case_od"]),
    step=0.001,
    format="%.3f"
)

wall_thickness = st.sidebar.number_input(
    "Espesor nominal, in",
    value=float(meta["case_thick"]),
    step=0.001,
    format="%.3f"
)

nominal_id = st.sidebar.number_input(
    "ID nominal, in",
    value=float(meta.get("case_id", case_od - 2 * wall_thickness)),
    step=0.001,
    format="%.3f"
)

st.sidebar.header("Criterios de alerta")

umbral_problema = st.sidebar.slider(
    "Umbral de problema sostenido, %",
    10,
    100,
    60
)

ventana_sostenida_ft = st.sidebar.number_input(
    "Ventana sostenida, ft",
    value=5.0,
    min_value=0.5,
    max_value=50.0,
    step=0.5,
    format="%.1f"
)

restriction_ref = st.sidebar.number_input(
    "Referencia restricción IDMN, in",
    value=0.250,
    step=0.010,
    format="%.3f"
)

ovality_ref = st.sidebar.number_input(
    "Referencia ovalidad, in",
    value=0.250,
    step=0.010,
    format="%.3f"
)

eccentricity_ref = st.sidebar.number_input(
    "Referencia excentricidad, in",
    value=0.200,
    step=0.010,
    format="%.3f"
)

jump_ref = st.sidebar.number_input(
    "Referencia salto brusco, in",
    value=0.100,
    step=0.010,
    format="%.3f"
)

max_points = st.sidebar.slider(
    "Puntos máximos para 3D",
    200,
    3000,
    1200,
    100
)


st.subheader("Resumen del archivo")

c1, c2, c3, c4 = st.columns(4)

c1.metric("OD casing", f"{case_od:.3f} in")
c2.metric("ID nominal", f"{nominal_id:.3f} in")
c3.metric("Espesor nominal", f"{wall_thickness:.3f} in")
c4.metric("Fuente", meta["fuente"])

st.write(f"Pozo: **{meta.get('pozo', '')}**")
st.write(f"Campo: **{meta.get('campo', '')}**")


st.subheader("Rangos de clasificación del problema sostenido")
st.dataframe(RANGOS_PROBLEMA, use_container_width=True, hide_index=True)

st.caption(
    "Nota técnica: el score de problema sostenido no es un porcentaje directo de rotura. "
    "Es un índice de alerta calculado con una ventana móvil para reducir falsos positivos por picos puntuales."
)


st.subheader("Vista previa de datos leídos")
st.dataframe(df.head(20), use_container_width=True)


columnas = list(df.columns)

depth_default = buscar_columna(columnas, ["DEPT", "Depth"])
idmn_default = buscar_columna(columnas, ["IDMN"])
idav_default = buscar_columna(columnas, ["IDAV"])
idmx_default = buscar_columna(columnas, ["IDMX"])

st.subheader("Mapeo de columnas")

m1, m2, m3, m4 = st.columns(4)

with m1:
    col_depth = st.selectbox(
        "Profundidad",
        columnas,
        index=columnas.index(depth_default) if depth_default in columnas else 0
    )

with m2:
    col_idmn = st.selectbox(
        "ID mínimo",
        columnas,
        index=columnas.index(idmn_default) if idmn_default in columnas else 0
    )

with m3:
    col_idav = st.selectbox(
        "ID promedio",
        columnas,
        index=columnas.index(idav_default) if idav_default in columnas else 0
    )

with m4:
    col_idmx = st.selectbox(
        "ID máximo",
        columnas,
        index=columnas.index(idmx_default) if idmx_default in columnas else 0
    )


try:
    data, id_arm_cols = procesar_datos(
        df,
        col_depth,
        col_idmn,
        col_idav,
        col_idmx,
        case_od,
        nominal_id,
        wall_thickness,
        restriction_ref,
        ovality_ref,
        eccentricity_ref,
        jump_ref,
        ventana_sostenida_ft
    )
except Exception as e:
    st.error(f"No pude procesar los datos: {e}")
    st.stop()


if data.empty:
    st.error("No quedaron datos válidos después de limpiar el archivo.")
    st.stop()


st.subheader("Filtro de profundidad")

min_depth = float(data["depth_ft"].min())
max_depth = float(data["depth_ft"].max())

rango = st.slider(
    "Rango MD, ft",
    min_value=min_depth,
    max_value=max_depth,
    value=(min_depth, max_depth)
)

data_filtrada = data[
    (data["depth_ft"] >= rango[0]) &
    (data["depth_ft"] <= rango[1])
].copy()


k1, k2, k3, k4, k5, k6 = st.columns(6)

k1.metric("MD inicial", f"{data_filtrada['depth_ft'].min():.2f} ft")
k2.metric("MD final", f"{data_filtrada['depth_ft'].max():.2f} ft")
k3.metric("Máx. problema sostenido", f"{data_filtrada['problem_score_pct'].max():.1f} %")
k4.metric("Máx. pico puntual", f"{data_filtrada['spike_score_pct'].max():.1f} %")
k5.metric("Menor IDMN", f"{data_filtrada['id_min_in'].min():.3f} in")
k6.metric("Integridad mínima", f"{data_filtrada['integrity_pct'].min():.1f} %")


fuera_rango = int(data_filtrada["out_of_physical_range"].sum())

if fuera_rango > 0:
    st.warning(
        f"Hay {fuera_rango} puntos donde IDMX supera el OD del casing. "
        "Estos puntos deben revisarse como lectura fuera de rango físico o zona severa."
    )


st.subheader("Tubular 3D coloreado por problema sostenido del casing")
st.info(
    "Pasa el cursor sobre el casing o sobre la línea negra central para ver MD, tipo de alerta, problema sostenido, "
    "pico puntual, desgaste, integridad, IDMN, IDAV, IDMX, espesor remanente y motivo probable."
)

st.plotly_chart(
    grafico_3d(data_filtrada, id_arm_cols, max_points, umbral_problema),
    use_container_width=True
)


st.subheader("Tracks de problema sostenido, picos puntuales y variables de casing")
st.plotly_chart(grafico_tracks(data_filtrada, umbral_problema), use_container_width=True)


st.subheader("Tracks IDMN, IDAV e IDMX")
st.plotly_chart(grafico_id(data_filtrada), use_container_width=True)


st.subheader("Profundidades con mayor problema sostenido")

top = data_filtrada.sort_values(
    [
        "problem_score_pct",
        "restriction_score_sustained_pct",
        "ovality_score_sustained_pct",
        "metal_loss_pct",
        "eccentricity_score_sustained_pct"
    ],
    ascending=[False, False, False, False, False]
).head(30)

columnas_top = [
    "depth_ft",
    "alert_type",
    "problem_score_pct",
    "spike_score_pct",
    "problem_class",
    "probable_cause",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "remaining_wall_in",
    "integrity_pct",
    "metal_loss_pct",
    "restriction_score_sustained_pct",
    "id_restriction_min_in",
    "ovality_calc_in",
    "ovality_score_sustained_pct",
    "eccentricity_in",
    "eccentricity_score_sustained_pct",
    "jump_score_sustained_pct",
    "out_of_physical_range"
]

st.dataframe(top[columnas_top].round(4), use_container_width=True)


st.subheader("Revisión rápida de zona 350 ft a 450 ft")

zona_350_450 = data[
    (data["depth_ft"] >= 350) &
    (data["depth_ft"] <= 450)
].copy()

if zona_350_450.empty:
    st.info("El archivo no contiene datos entre 350 ft y 450 ft.")
else:
    st.dataframe(
        zona_350_450.sort_values("problem_score_pct", ascending=False)[columnas_top].head(40).round(4),
        use_container_width=True
    )


st.subheader("Picos puntuales que NO necesariamente son daño sostenido")

picos = data_filtrada[
    (data_filtrada["spike_score_pct"] >= 60) &
    (data_filtrada["problem_score_pct"] < 35)
].copy()

if picos.empty:
    st.success("No se detectaron picos puntuales aislados relevantes dentro del rango filtrado.")
else:
    st.dataframe(
        picos.sort_values("spike_score_pct", ascending=False)[columnas_top].head(30).round(4),
        use_container_width=True
    )


st.subheader("Intervalos críticos sostenidos")

intervalos = intervalos_criticos(data_filtrada, umbral_problema)

if intervalos.empty:
    st.success("No se detectaron intervalos sostenidos por encima del umbral seleccionado.")
else:
    st.dataframe(intervalos.round(4), use_container_width=True)


st.subheader("Tabla procesada completa")

columnas_salida = [
    "depth_ft",
    "alert_type",
    "problem_score_pct",
    "spike_score_pct",
    "problem_class",
    "probable_cause",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "case_od_in",
    "nominal_id_in",
    "nominal_wall_in",
    "remaining_wall_raw_in",
    "remaining_wall_in",
    "integrity_raw_pct",
    "integrity_pct",
    "metal_loss_pct",
    "id_enlargement_max_in",
    "id_restriction_min_in",
    "diameter_spread_in",
    "ovality_calc_in",
    "ovality_las_in",
    "eccentricity_in",
    "wear_score_raw_pct",
    "wear_score_sustained_pct",
    "restriction_score_raw_pct",
    "restriction_score_sustained_pct",
    "ovality_score_raw_pct",
    "ovality_score_sustained_pct",
    "eccentricity_score_raw_pct",
    "eccentricity_score_sustained_pct",
    "jump_score_raw_pct",
    "jump_score_sustained_pct",
    "out_of_physical_range",
    "integrity_class",
    "smoothing_window_points"
]

st.dataframe(data_filtrada[columnas_salida].round(4), use_container_width=True)


csv = data_filtrada[columnas_salida].to_csv(index=False).encode("utf-8")

st.download_button(
    "Descargar tabla procesada CSV",
    data=csv,
    file_name="casing_integrity_sustained_problem_analysis.csv",
    mime="text/csv"
)
