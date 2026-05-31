import re
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Casing Integrity 3D Viewer", layout="wide")

st.title("Casing Integrity 3D Viewer")
st.caption(
    "Sube un archivo LAS, Excel o CSV del registro caliper para ver el tubular en 3D "
    "y detectar mayor desgaste."
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
    ).replace([-999.25, -999.2500, -999, -999.0], np.nan)


def buscar_columna(columnas, opciones):
    columnas_limpias = {str(c).strip().upper(): c for c in columnas}

    for opcion in opciones:
        if opcion.upper() in columnas_limpias:
            return columnas_limpias[opcion.upper()]

    return None


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
            break

    if indice_a is None:
        raise ValueError("No se encontró la sección ~A del archivo LAS.")

    if not curvas:
        raise ValueError("No se encontraron curvas en la sección ~Curve.")

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
    df = df.replace([-999.25, -999.2500, -999, -999.0], np.nan)

    case_od = parse_float(parametros.get("CASEOD"), 4.500)
    case_id = parse_float(parametros.get("CASEID"), None)
    case_thick = parse_float(parametros.get("CASETHCK"), 0.224)

    if case_id is None:
        case_id = case_od - 2 * case_thick

    df["Case_OD"] = case_od
    df["Nominal_ID"] = case_id
    df["Wall_Thickness"] = case_thick

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
        ):
            return leer_las_desde_texto(texto_unido)

        df = pd.read_excel(BytesIO(datos))

        meta = {
            "pozo": "",
            "campo": "",
            "compania": "",
            "case_od": 4.500,
            "case_id": 4.052,
            "case_thick": 0.224,
            "fuente": "Excel tabular"
        }

        return df, meta

    if nombre.endswith(".csv"):
        df = pd.read_csv(archivo)

        meta = {
            "pozo": "",
            "campo": "",
            "compania": "",
            "case_od": 4.500,
            "case_id": 4.052,
            "case_thick": 0.224,
            "fuente": "CSV"
        }

        return df, meta

    raise ValueError("Formato no soportado. Usa LAS, Excel o CSV.")


def clasificar(integridad):
    if integridad >= 80:
        return "Aceptable"
    if integridad >= 60:
        return "Moderado"
    if integridad >= 40:
        return "Crítico"

    return "Severo"


def procesar_datos(
    df,
    col_depth,
    col_idmn,
    col_idav,
    col_idmx,
    col_id11,
    col_id12,
    case_od,
    nominal_id,
    wall_thickness
):
    data = pd.DataFrame()

    data["depth_ft"] = limpiar_numero(df[col_depth])
    data["id_min_in"] = limpiar_numero(df[col_idmn])
    data["id_avg_in"] = limpiar_numero(df[col_idav])
    data["id_max_in"] = limpiar_numero(df[col_idmx])

    if col_id11:
        data["id11_in"] = limpiar_numero(df[col_id11])
    else:
        data["id11_in"] = data["id_avg_in"]

    if col_id12:
        data["id12_in"] = limpiar_numero(df[col_id12])
    else:
        data["id12_in"] = data["id_avg_in"]

    data["case_od_in"] = case_od
    data["nominal_id_in"] = nominal_id
    data["nominal_wall_in"] = wall_thickness

    data = data.dropna(subset=["depth_ft", "id_min_in", "id_avg_in", "id_max_in"])
    data = data.sort_values("depth_ft")

    data["remaining_wall_raw_in"] = (data["case_od_in"] - data["id_max_in"]) / 2
    data["remaining_wall_in"] = data["remaining_wall_raw_in"].clip(lower=0)

    data["integrity_raw_pct"] = 100 * data["remaining_wall_raw_in"] / data["nominal_wall_in"]
    data["integrity_pct"] = data["integrity_raw_pct"].clip(lower=0, upper=100)

    data["metal_loss_pct"] = 100 - data["integrity_pct"]
    data["id_enlargement_max_in"] = data["id_max_in"] - data["nominal_id_in"]
    data["ovality_in"] = data["id_max_in"] - data["id_min_in"]

    data["out_of_physical_range"] = data["id_max_in"] > data["case_od_in"]
    data["class"] = data["integrity_pct"].apply(clasificar)

    return data


def grafico_3d(data, max_points):
    if len(data) > max_points:
        indices = np.linspace(0, len(data) - 1, max_points).astype(int)
        data = data.iloc[indices].copy()

    theta = np.linspace(0, 2 * np.pi, 96)
    depth = data["depth_ft"].to_numpy()

    id11 = data["id11_in"].fillna(data["id_avg_in"]).to_numpy()
    id12 = data["id12_in"].fillna(data["id_avg_in"]).to_numpy()
    case_od = data["case_od_in"].to_numpy()

    id11 = np.minimum(id11, case_od)
    id12 = np.minimum(id12, case_od)

    rx = id11 / 2
    ry = id12 / 2

    theta_grid, depth_grid = np.meshgrid(theta, depth)

    rx_grid = np.repeat(rx.reshape(-1, 1), len(theta), axis=1)
    ry_grid = np.repeat(ry.reshape(-1, 1), len(theta), axis=1)

    x = rx_grid * np.cos(theta_grid)
    y = ry_grid * np.sin(theta_grid)
    z = depth_grid

    desgaste = data["metal_loss_pct"].fillna(0).to_numpy()
    integridad = data["integrity_pct"].fillna(0).to_numpy()
    espesor = data["remaining_wall_in"].fillna(0).to_numpy()
    idmx = data["id_max_in"].fillna(0).to_numpy()

    desgaste_grid = np.repeat(desgaste.reshape(-1, 1), len(theta), axis=1)

    custom_surface = np.stack(
        [
            desgaste_grid,
            np.repeat(integridad.reshape(-1, 1), len(theta), axis=1),
            np.repeat(espesor.reshape(-1, 1), len(theta), axis=1),
            np.repeat(idmx.reshape(-1, 1), len(theta), axis=1),
        ],
        axis=-1
    )

    custom_centro = np.column_stack(
        [
            desgaste,
            integridad,
            espesor,
            idmx
        ]
    )

    fig = go.Figure()

    fig.add_trace(
        go.Surface(
            x=x,
            y=y,
            z=z,
            surfacecolor=desgaste_grid,
            customdata=custom_surface,
            cmin=0,
            cmax=100,
            colorscale=[
                [0.00, "green"],
                [0.40, "lightgreen"],
                [0.60, "yellow"],
                [0.80, "orange"],
                [1.00, "red"],
            ],
            colorbar=dict(title="Desgaste %"),
            hovertemplate=(
                "MD: %{z:.2f} ft<br>"
                "Desgaste: %{customdata[0]:.1f} %<br>"
                "Integridad: %{customdata[1]:.1f} %<br>"
                "Espesor remanente: %{customdata[2]:.3f} in<br>"
                "IDMX: %{customdata[3]:.3f} in"
                "<extra></extra>"
            ),
            name="Tubular"
        )
    )

    fig.add_trace(
        go.Scatter3d(
            x=np.zeros(len(depth)),
            y=np.zeros(len(depth)),
            z=depth,
            mode="lines+markers",
            line=dict(width=5, color="black"),
            marker=dict(size=4, color=desgaste, colorscale="Turbo", cmin=0, cmax=100),
            customdata=custom_centro,
            name="Línea de lectura",
            hovertemplate=(
                "<b>Lectura del casing</b><br>"
                "MD: %{z:.2f} ft<br>"
                "Desgaste: %{customdata[0]:.1f} %<br>"
                "Integridad: %{customdata[1]:.1f} %<br>"
                "Espesor remanente: %{customdata[2]:.3f} in<br>"
                "IDMX: %{customdata[3]:.3f} in"
                "<extra></extra>"
            ),
        )
    )

    fig.update_layout(
        height=750,
        scene=dict(
            xaxis_title="X, in",
            yaxis_title="Y, in",
            zaxis_title="MD, ft",
            zaxis=dict(autorange="reversed"),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=4),
        ),
        margin=dict(l=0, r=0, t=20, b=0),
        legend=dict(orientation="h")
    )

    return fig


def grafico_tracks(data):
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=data["metal_loss_pct"],
            y=data["depth_ft"],
            mode="lines",
            name="Desgaste, %"
        )
    )

    fig.add_trace(
        go.Scatter(
            x=data["integrity_pct"],
            y=data["depth_ft"],
            mode="lines",
            name="Integridad, %"
        )
    )

    fig.add_trace(
        go.Scatter(
            x=data["id_max_in"],
            y=data["depth_ft"],
            mode="lines",
            name="IDMX, in",
            xaxis="x2"
        )
    )

    fig.update_layout(
        height=520,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Integridad / desgaste, %", range=[0, 100]),
        xaxis2=dict(title="IDMX, in", overlaying="x", side="top"),
        legend=dict(orientation="h"),
        margin=dict(l=20, r=20, t=50, b=20),
    )

    return fig


def intervalos_criticos(data, umbral):
    data = data.sort_values("depth_ft").copy()
    data["critico"] = data["integrity_pct"] < umbral

    intervalos = []
    bloque = []

    for _, row in data.iterrows():
        if row["critico"]:
            bloque.append(row)
        else:
            if bloque:
                b = pd.DataFrame(bloque)

                intervalos.append({
                    "from_ft": b["depth_ft"].min(),
                    "to_ft": b["depth_ft"].max(),
                    "min_integrity_pct": b["integrity_pct"].min(),
                    "max_metal_loss_pct": b["metal_loss_pct"].max(),
                    "min_wall_in": b["remaining_wall_in"].min(),
                    "max_id_in": b["id_max_in"].max(),
                    "max_ovality_in": b["ovality_in"].max()
                })

                bloque = []

    if bloque:
        b = pd.DataFrame(bloque)

        intervalos.append({
            "from_ft": b["depth_ft"].min(),
            "to_ft": b["depth_ft"].max(),
            "min_integrity_pct": b["integrity_pct"].min(),
            "max_metal_loss_pct": b["metal_loss_pct"].max(),
            "min_wall_in": b["remaining_wall_in"].min(),
            "max_id_in": b["id_max_in"].max(),
            "max_ovality_in": b["ovality_in"].max()
        })

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

nominal_id = case_od - 2 * wall_thickness

umbral = st.sidebar.slider("Umbral crítico de integridad, %", 10, 100, 60)
max_points = st.sidebar.slider("Puntos máximos para 3D", 200, 3000, 1200, 100)


st.subheader("Resumen del archivo")

c1, c2, c3, c4 = st.columns(4)

c1.metric("OD casing", f"{case_od:.3f} in")
c2.metric("ID nominal", f"{nominal_id:.3f} in")
c3.metric("Espesor nominal", f"{wall_thickness:.3f} in")
c4.metric("Fuente", meta["fuente"])

st.write(f"Pozo: **{meta.get('pozo', '')}**")
st.write(f"Campo: **{meta.get('campo', '')}**")


st.subheader("Vista previa de datos leídos")
st.dataframe(df.head(20), use_container_width=True)


columnas = list(df.columns)

depth_default = buscar_columna(columnas, ["DEPT", "Depth"])
idmn_default = buscar_columna(columnas, ["IDMN"])
idav_default = buscar_columna(columnas, ["IDAV"])
idmx_default = buscar_columna(columnas, ["IDMX"])
id11_default = buscar_columna(columnas, ["ID11"])
id12_default = buscar_columna(columnas, ["ID12"])


st.subheader("Mapeo de columnas")

m1, m2, m3 = st.columns(3)

with m1:
    col_depth = st.selectbox(
        "Profundidad",
        columnas,
        index=columnas.index(depth_default) if depth_default in columnas else 0
    )

    col_idmn = st.selectbox(
        "ID mínimo",
        columnas,
        index=columnas.index(idmn_default) if idmn_default in columnas else 0
    )

with m2:
    col_idav = st.selectbox(
        "ID promedio",
        columnas,
        index=columnas.index(idav_default) if idav_default in columnas else 0
    )

    col_idmx = st.selectbox(
        "ID máximo",
        columnas,
        index=columnas.index(idmx_default) if idmx_default in columnas else 0
    )

with m3:
    opciones = [None] + columnas

    col_id11 = st.selectbox(
        "Diámetro 11",
        opciones,
        index=opciones.index(id11_default) if id11_default in opciones else 0
    )

    col_id12 = st.selectbox(
        "Diámetro 12",
        opciones,
        index=opciones.index(id12_default) if id12_default in opciones else 0
    )


try:
    data = procesar_datos(
        df,
        col_depth,
        col_idmn,
        col_idav,
        col_idmx,
        col_id11,
        col_id12,
        case_od,
        nominal_id,
        wall_thickness
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


k1, k2, k3, k4, k5 = st.columns(5)

k1.metric("MD inicial", f"{data_filtrada['depth_ft'].min():.2f} ft")
k2.metric("MD final", f"{data_filtrada['depth_ft'].max():.2f} ft")
k3.metric("Integridad mínima", f"{data_filtrada['integrity_pct'].min():.1f} %")
k4.metric("Mayor desgaste", f"{data_filtrada['metal_loss_pct'].max():.1f} %")
k5.metric("Espesor mínimo", f"{data_filtrada['remaining_wall_in'].min():.3f} in")


fuera_rango = int(data_filtrada["out_of_physical_range"].sum())

if fuera_rango > 0:
    st.warning(
        f"Hay {fuera_rango} puntos donde IDMX supera el OD del casing. "
        "Esos puntos aparecen como 100 % de desgaste, pero deben revisarse como posible dato anómalo o lectura fuera de rango físico."
    )


st.subheader("Tubular 3D coloreado por desgaste")
st.info("Para ver la lectura exacta, pasa el mouse sobre la línea central negra del tubular.")
st.plotly_chart(grafico_3d(data_filtrada, max_points), use_container_width=True)


st.subheader("Tracks de integridad, desgaste e IDMX")
st.plotly_chart(grafico_tracks(data_filtrada), use_container_width=True)


st.subheader("Profundidades con mayor desgaste")

top = data_filtrada.sort_values(
    ["metal_loss_pct", "id_enlargement_max_in", "id_max_in"],
    ascending=[False, False, False]
).head(20)

columnas_top = [
    "depth_ft",
    "id_max_in",
    "id_avg_in",
    "id_min_in",
    "remaining_wall_in",
    "integrity_pct",
    "metal_loss_pct",
    "id_enlargement_max_in",
    "ovality_in",
    "out_of_physical_range",
    "class"
]

st.dataframe(top[columnas_top].round(4), use_container_width=True)


st.subheader("Intervalos críticos")

intervalos = intervalos_criticos(data_filtrada, umbral)

if intervalos.empty:
    st.success("No se detectaron intervalos por debajo del umbral seleccionado.")
else:
    st.dataframe(intervalos.round(4), use_container_width=True)


st.subheader("Tabla procesada completa")

columnas_salida = [
    "depth_ft",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "id11_in",
    "id12_in",
    "case_od_in",
    "nominal_id_in",
    "nominal_wall_in",
    "remaining_wall_raw_in",
    "remaining_wall_in",
    "integrity_raw_pct",
    "integrity_pct",
    "metal_loss_pct",
    "id_enlargement_max_in",
    "ovality_in",
    "out_of_physical_range",
    "class"
]

st.dataframe(data_filtrada[columnas_salida].round(4), use_container_width=True)


csv = data_filtrada[columnas_salida].to_csv(index=False).encode("utf-8")

st.download_button(
    "Descargar tabla procesada CSV",
    data=csv,
    file_name="casing_integrity_processed.csv",
    mime="text/csv"
)
