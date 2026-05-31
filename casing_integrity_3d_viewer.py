import re
from io import BytesIO

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


st.set_page_config(page_title="Casing Integrity 3D Viewer", layout="wide")

st.title("Casing Integrity 3D Viewer")
st.caption(
    "Sube un archivo LAS, Excel o CSV. "
    "La app clasifica el casing por desviación del ID nominal: colapso, buen estado o desgaste."
)


NULL_VALUES = [-999.25, -999.2500, -999, -999.0]


RANGOS_ESTADO = pd.DataFrame(
    [
        {
            "Estado": "Colapso Crítico",
            "Rango respecto al ID nominal": "ID - 40% a -100%",
            "Interpretación": "Reducción extrema del diámetro interno. Revisar como condición crítica."
        },
        {
            "Estado": "Colapso Severo",
            "Rango respecto al ID nominal": "ID - 20% a -40%",
            "Interpretación": "Reducción severa del diámetro interno."
        },
        {
            "Estado": "Colapso Moderado",
            "Rango respecto al ID nominal": "ID - 10% a -20%",
            "Interpretación": "Reducción moderada del diámetro interno."
        },
        {
            "Estado": "Colapso Leve",
            "Rango respecto al ID nominal": "ID - 0% a -10%",
            "Interpretación": "Reducción leve del diámetro interno."
        },
        {
            "Estado": "Buen estado",
            "Rango respecto al ID nominal": "Cercano al ID nominal",
            "Interpretación": "Sin desviación relevante frente al ID nominal."
        },
        {
            "Estado": "Desgaste Leve",
            "Rango respecto al ID nominal": "ID + 0% a +10%",
            "Interpretación": "Aumento leve del diámetro interno."
        },
        {
            "Estado": "Desgaste Moderado",
            "Rango respecto al ID nominal": "ID + 10% a +20%",
            "Interpretación": "Aumento moderado del diámetro interno."
        },
        {
            "Estado": "Desgaste Severo",
            "Rango respecto al ID nominal": "ID + 20% a +40%",
            "Interpretación": "Aumento severo del diámetro interno."
        },
        {
            "Estado": "Desgaste Crítico",
            "Rango respecto al ID nominal": "ID + 40% a +100%",
            "Interpretación": "Aumento extremo del diámetro interno. Revisar como condición crítica."
        },
    ]
)


COLOR_SCALE_ESTADO = [
    [0.00, "#2b004f"],
    [0.30, "#0033cc"],
    [0.40, "#00a6ff"],
    [0.45, "#4ddbc8"],
    [0.50, "#00a651"],
    [0.55, "#ffff00"],
    [0.60, "#ff9900"],
    [0.70, "#ff0000"],
    [1.00, "#7a0000"],
]


def parse_float(texto, default=None):
    if texto is None:
        return default

    texto = str(texto).replace(",", ".")
    match = re.search(r"[-+]?\d+(?:\.\d+)?", texto)

    if match:
        return float(match.group(0))

    return default


def fmt(valor, decimales=2, unidad=""):
    try:
        if pd.isna(valor):
            return "N/D"

        return f"{float(valor):.{decimales}f}{unidad}"

    except Exception:
        return "N/D"


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


def clasificar_porcentaje_desgaste(pct):
    if pct >= 40:
        return "Desgaste Crítico"
    if pct >= 20:
        return "Desgaste Severo"
    if pct >= 10:
        return "Desgaste Moderado"
    if pct > 0:
        return "Desgaste Leve"

    return "Buen estado"


def clasificar_porcentaje_colapso(pct):
    if pct >= 40:
        return "Colapso Crítico"
    if pct >= 20:
        return "Colapso Severo"
    if pct >= 10:
        return "Colapso Moderado"
    if pct > 0:
        return "Colapso Leve"

    return "Buen estado"


def clasificar_estado(row, tolerancia_buen_estado):
    desgaste = row["desgaste_id_pct"]
    colapso = row["colapso_id_pct"]

    if desgaste <= tolerancia_buen_estado and colapso <= tolerancia_buen_estado:
        return "Buen estado"

    if colapso > desgaste:
        return clasificar_porcentaje_colapso(colapso)

    return clasificar_porcentaje_desgaste(desgaste)


def tipo_dominante(row, tolerancia_buen_estado):
    desgaste = row["desgaste_id_pct"]
    colapso = row["colapso_id_pct"]

    if desgaste <= tolerancia_buen_estado and colapso <= tolerancia_buen_estado:
        return "Buen estado"

    if colapso > desgaste:
        return "Colapso"

    return "Desgaste"


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


def procesar_datos(
    df,
    col_depth,
    col_idmn,
    col_idav,
    col_idmx,
    case_od,
    nominal_id,
    wall_thickness,
    tolerancia_buen_estado
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

    radial_cols = []

    for i in range(1, 49):
        col_id = buscar_columna(df.columns, [f"ID{i:02d}", f"ID{i}"])

        if col_id:
            nuevo = f"dia_arm_{i:02d}_in"
            data[nuevo] = limpiar_numero(df[col_id])
            radial_cols.append(nuevo)

    if len(radial_cols) < 6:
        radial_cols = []

        for i in range(1, 49):
            col_r = buscar_columna(df.columns, [f"R{i:02d}", f"R{i}"])

            if col_r:
                nuevo = f"dia_arm_{i:02d}_in"
                data[nuevo] = limpiar_numero(df[col_r]) * 2.0
                radial_cols.append(nuevo)

    data = data.dropna(subset=["depth_ft", "id_min_in", "id_avg_in", "id_max_in"])
    data = data.sort_values("depth_ft").reset_index(drop=True)

    data["desgaste_id_in"] = data["id_max_in"] - data["nominal_id_in"]
    data["colapso_id_in"] = data["nominal_id_in"] - data["id_min_in"]

    data["desgaste_id_pct"] = (
        data["desgaste_id_in"].clip(lower=0) / data["nominal_id_in"] * 100
    ).clip(lower=0, upper=100)

    data["colapso_id_pct"] = (
        data["colapso_id_in"].clip(lower=0) / data["nominal_id_in"] * 100
    ).clip(lower=0, upper=100)

    data["estado_casing"] = data.apply(
        lambda row: clasificar_estado(row, tolerancia_buen_estado),
        axis=1
    )

    data["tipo_dominante"] = data.apply(
        lambda row: tipo_dominante(row, tolerancia_buen_estado),
        axis=1
    )

    data["indice_color_pct"] = np.where(
        data["tipo_dominante"] == "Colapso",
        -data["colapso_id_pct"],
        data["desgaste_id_pct"]
    )

    data.loc[data["estado_casing"] == "Buen estado", "indice_color_pct"] = 0
    data["indice_color_pct"] = data["indice_color_pct"].clip(lower=-100, upper=100)

    data["remaining_wall_raw_in"] = (data["case_od_in"] - data["id_max_in"]) / 2
    data["remaining_wall_in"] = data["remaining_wall_raw_in"].clip(lower=0)

    data["integrity_raw_pct"] = 100 * data["remaining_wall_raw_in"] / data["nominal_wall_in"]
    data["integrity_pct"] = data["integrity_raw_pct"].clip(lower=0, upper=100)

    data["metal_loss_wall_pct"] = 100 - data["integrity_pct"]
    data["metal_loss_wall_pct"] = data["metal_loss_wall_pct"].clip(lower=0, upper=100)

    data["diameter_spread_in"] = data["id_max_in"] - data["id_min_in"]
    data["ovality_calc_in"] = data["diameter_spread_in"].clip(lower=0)

    data["out_of_physical_range"] = data["id_max_in"] > data["case_od_in"]

    return data, radial_cols


def textos_hover(data):
    textos = []

    for _, row in data.iterrows():
        texto = (
            f"<b>Lectura del casing</b><br>"
            f"MD: {fmt(row['depth_ft'], 2, ' ft')}<br>"
            f"Estado: {row['estado_casing']}<br>"
            f"Tipo dominante: {row['tipo_dominante']}<br>"
            f"Índice color: {fmt(row['indice_color_pct'], 2, ' %')}<br>"
            f"Desgaste respecto al ID: {fmt(row['desgaste_id_pct'], 2, ' %')}<br>"
            f"Colapso respecto al ID: {fmt(row['colapso_id_pct'], 2, ' %')}<br>"
            f"ID nominal: {fmt(row['nominal_id_in'], 3, ' in')}<br>"
            f"IDMN: {fmt(row['id_min_in'], 3, ' in')}<br>"
            f"IDAV: {fmt(row['id_avg_in'], 3, ' in')}<br>"
            f"IDMX: {fmt(row['id_max_in'], 3, ' in')}<br>"
            f"Aumento IDMX: {fmt(row['desgaste_id_in'], 3, ' in')}<br>"
            f"Reducción IDMN: {fmt(row['colapso_id_in'], 3, ' in')}<br>"
            f"Ovalidad calculada: {fmt(row['ovality_calc_in'], 3, ' in')}<br>"
            f"Espesor remanente por IDMX: {fmt(row['remaining_wall_in'], 3, ' in')}<br>"
            f"Integridad por pared: {fmt(row['integrity_pct'], 1, ' %')}<br>"
            f"Pérdida de pared por IDMX: {fmt(row['metal_loss_wall_pct'], 1, ' %')}"
        )

        textos.append(texto)

    return textos


def construir_superficie(data, radial_cols):
    if len(radial_cols) >= 6:
        diametros = data[radial_cols].copy()

        for col in radial_cols:
            diametros[col] = diametros[col].fillna(data["id_avg_in"])

        radios = diametros.to_numpy(dtype=float) / 2
        radios = np.clip(radios, 0, data["case_od_in"].to_numpy().reshape(-1, 1) / 2)

        theta = np.linspace(0, 2 * np.pi, len(radial_cols), endpoint=False)

        radios = np.column_stack([radios, radios[:, 0]])
        theta = np.append(theta, 2 * np.pi)

    else:
        theta = np.linspace(0, 2 * np.pi, 96)

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


def grafico_3d(data, radial_cols, max_points):
    if len(data) > max_points:
        indices = np.linspace(0, len(data) - 1, max_points).astype(int)
        data_plot = data.iloc[indices].copy()
    else:
        data_plot = data.copy()

    x, y, z = construir_superficie(data_plot, radial_cols)

    indice = data_plot["indice_color_pct"].fillna(0).to_numpy()
    indice_grid = np.repeat(indice.reshape(-1, 1), x.shape[1], axis=1)

    textos = textos_hover(data_plot)

    fig = go.Figure()

    fig.add_trace(
        go.Surface(
            x=x,
            y=y,
            z=z,
            surfacecolor=indice_grid,
            cmin=-100,
            cmax=100,
            colorscale=COLOR_SCALE_ESTADO,
            colorbar=dict(
                title="Estado casing",
                tickvals=[-70, -30, -15, -5, 0, 5, 15, 30, 70],
                ticktext=[
                    "Colapso crítico",
                    "Colapso severo",
                    "Colapso moderado",
                    "Colapso leve",
                    "Buen estado",
                    "Desgaste leve",
                    "Desgaste moderado",
                    "Desgaste severo",
                    "Desgaste crítico"
                ]
            ),
            hoverinfo="skip",
            name="Casing"
        )
    )

    cantidad_angulos = x.shape[1]
    angulos_lectura = np.linspace(0, cantidad_angulos - 1, min(32, cantidad_angulos)).astype(int)

    x_hover = x[:, angulos_lectura].reshape(-1)
    y_hover = y[:, angulos_lectura].reshape(-1)
    z_hover = z[:, angulos_lectura].reshape(-1)

    textos_hover_superficie = np.repeat(np.array(textos, dtype=object), len(angulos_lectura))
    indice_hover = np.repeat(indice, len(angulos_lectura))

    fig.add_trace(
        go.Scatter3d(
            x=x_hover,
            y=y_hover,
            z=z_hover,
            mode="markers",
            marker=dict(
                size=7,
                color=indice_hover,
                colorscale=COLOR_SCALE_ESTADO,
                cmin=-100,
                cmax=100,
                opacity=0.25
            ),
            hovertext=textos_hover_superficie,
            hovertemplate="%{hovertext}<extra></extra>",
            hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
            name="Lectura sobre casing",
            showlegend=True
        )
    )

    fig.add_annotation(
        text=(
            "<b>Escala:</b> Colapso crítico ≤ -40% | Colapso severo -20% a -40% | "
            "Colapso moderado -10% a -20% | Colapso leve 0% a -10% | "
            "Buen estado ≈ ID nominal | Desgaste leve 0% a 10% | "
            "Desgaste moderado 10% a 20% | Desgaste severo 20% a 40% | "
            "Desgaste crítico ≥ 40%"
        ),
        xref="paper",
        yref="paper",
        x=0.01,
        y=1.07,
        showarrow=False,
        align="left",
        bgcolor="rgba(255,255,255,0.92)",
        bordercolor="gray",
        borderwidth=1
    )

    fig.update_layout(
        height=780,
        scene=dict(
            xaxis_title="X, in",
            yaxis_title="Y, in",
            zaxis_title="MD, ft",
            zaxis=dict(autorange="reversed"),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=4),
        ),
        margin=dict(l=0, r=0, t=80, b=0),
        legend=dict(orientation="h"),
        hovermode="closest"
    )

    return fig


def grafico_estado(data):
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=data["indice_color_pct"],
            y=data["depth_ft"],
            mode="lines",
            name="Índice estado casing, %"
        )
    )

    fig.add_vline(x=-40, line_dash="dot", annotation_text="Colapso crítico")
    fig.add_vline(x=-20, line_dash="dot", annotation_text="Colapso severo")
    fig.add_vline(x=-10, line_dash="dot", annotation_text="Colapso moderado")
    fig.add_vline(x=0, line_dash="dash", annotation_text="ID nominal")
    fig.add_vline(x=10, line_dash="dot", annotation_text="Desgaste moderado")
    fig.add_vline(x=20, line_dash="dot", annotation_text="Desgaste severo")
    fig.add_vline(x=40, line_dash="dot", annotation_text="Desgaste crítico")

    fig.update_layout(
        height=560,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Desviación respecto al ID nominal, %", range=[-100, 100]),
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


def crear_intervalos(data):
    data = data.sort_values("depth_ft").copy()

    intervalos = []
    estado_actual = None
    bloque = []

    for _, row in data.iterrows():
        estado = row["estado_casing"]

        if estado_actual is None:
            estado_actual = estado
            bloque = [row]
            continue

        if estado == estado_actual:
            bloque.append(row)
        else:
            b = pd.DataFrame(bloque)

            intervalos.append({
                "from_ft": b["depth_ft"].min(),
                "to_ft": b["depth_ft"].max(),
                "longitud_ft": b["depth_ft"].max() - b["depth_ft"].min(),
                "estado": estado_actual,
                "min_indice_pct": b["indice_color_pct"].min(),
                "max_indice_pct": b["indice_color_pct"].max(),
                "max_desgaste_id_pct": b["desgaste_id_pct"].max(),
                "max_colapso_id_pct": b["colapso_id_pct"].max(),
                "min_idmn_in": b["id_min_in"].min(),
                "max_idmx_in": b["id_max_in"].max(),
                "max_ovality_in": b["ovality_calc_in"].max()
            })

            estado_actual = estado
            bloque = [row]

    if bloque:
        b = pd.DataFrame(bloque)

        intervalos.append({
            "from_ft": b["depth_ft"].min(),
            "to_ft": b["depth_ft"].max(),
            "longitud_ft": b["depth_ft"].max() - b["depth_ft"].min(),
            "estado": estado_actual,
            "min_indice_pct": b["indice_color_pct"].min(),
            "max_indice_pct": b["indice_color_pct"].max(),
            "max_desgaste_id_pct": b["desgaste_id_pct"].max(),
            "max_colapso_id_pct": b["colapso_id_pct"].max(),
            "min_idmn_in": b["id_min_in"].min(),
            "max_idmx_in": b["id_max_in"].max(),
            "max_ovality_in": b["ovality_calc_in"].max()
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

nominal_id = st.sidebar.number_input(
    "ID nominal, in",
    value=float(meta.get("case_id", case_od - 2 * wall_thickness)),
    step=0.001,
    format="%.3f"
)

tolerancia_buen_estado = st.sidebar.number_input(
    "Tolerancia buen estado, %",
    value=0.50,
    min_value=0.0,
    max_value=5.0,
    step=0.10,
    format="%.2f"
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


st.subheader("Rangos de clasificación")
st.dataframe(RANGOS_ESTADO, use_container_width=True, hide_index=True)

st.caption(
    "Nota: desgaste se calcula con IDMX respecto al ID nominal. "
    "Colapso se calcula con IDMN respecto al ID nominal. "
    "El estado mostrado toma el efecto dominante entre desgaste y colapso."
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
    data, radial_cols = procesar_datos(
        df,
        col_depth,
        col_idmn,
        col_idav,
        col_idmx,
        case_od,
        nominal_id,
        wall_thickness,
        tolerancia_buen_estado
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
k3.metric("Máx. desgaste ID", f"{data_filtrada['desgaste_id_pct'].max():.2f} %")
k4.metric("Máx. colapso ID", f"{data_filtrada['colapso_id_pct'].max():.2f} %")
k5.metric("Menor IDMN", f"{data_filtrada['id_min_in'].min():.3f} in")
k6.metric("Mayor IDMX", f"{data_filtrada['id_max_in'].max():.3f} in")


fuera_rango = int(data_filtrada["out_of_physical_range"].sum())

if fuera_rango > 0:
    st.warning(
        f"Hay {fuera_rango} puntos donde IDMX supera el OD del casing. "
        "Estos puntos deben revisarse como lectura fuera de rango físico."
    )


st.subheader("Tubular 3D por estado del casing")
st.info(
    "Pasa el cursor sobre los puntos coloreados de la pared del casing para ver la lectura completa."
)

st.plotly_chart(
    grafico_3d(data_filtrada, radial_cols, max_points),
    use_container_width=True
)


st.subheader("Track de estado del casing")
st.plotly_chart(grafico_estado(data_filtrada), use_container_width=True)


st.subheader("Tracks IDMN, IDAV e IDMX")
st.plotly_chart(grafico_id(data_filtrada), use_container_width=True)


st.subheader("Profundidades más críticas")

top = data_filtrada.copy()
top["severidad_abs_pct"] = top["indice_color_pct"].abs()

top = top.sort_values(
    ["severidad_abs_pct", "desgaste_id_pct", "colapso_id_pct"],
    ascending=[False, False, False]
).head(30)

columnas_top = [
    "depth_ft",
    "estado_casing",
    "tipo_dominante",
    "indice_color_pct",
    "desgaste_id_pct",
    "colapso_id_pct",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "desgaste_id_in",
    "colapso_id_in",
    "ovality_calc_in",
    "remaining_wall_in",
    "integrity_pct",
    "metal_loss_wall_pct",
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
    zona_350_450["severidad_abs_pct"] = zona_350_450["indice_color_pct"].abs()

    st.dataframe(
        zona_350_450.sort_values("severidad_abs_pct", ascending=False)[columnas_top].head(60).round(4),
        use_container_width=True
    )


st.subheader("Intervalos por estado")

intervalos = crear_intervalos(data_filtrada)

if intervalos.empty:
    st.info("No se generaron intervalos.")
else:
    st.dataframe(intervalos.round(4), use_container_width=True)


st.subheader("Tabla procesada completa")

columnas_salida = [
    "depth_ft",
    "estado_casing",
    "tipo_dominante",
    "indice_color_pct",
    "desgaste_id_pct",
    "colapso_id_pct",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "case_od_in",
    "nominal_id_in",
    "nominal_wall_in",
    "desgaste_id_in",
    "colapso_id_in",
    "diameter_spread_in",
    "ovality_calc_in",
    "ovality_las_in",
    "eccentricity_in",
    "remaining_wall_raw_in",
    "remaining_wall_in",
    "integrity_raw_pct",
    "integrity_pct",
    "metal_loss_wall_pct",
    "out_of_physical_range"
]

st.dataframe(data_filtrada[columnas_salida].round(4), use_container_width=True)


csv = data_filtrada[columnas_salida].to_csv(index=False).encode("utf-8")

st.download_button(
    "Descargar tabla procesada CSV",
    data=csv,
    file_name="casing_estado_por_id_nominal.csv",
    mime="text/csv"
)
