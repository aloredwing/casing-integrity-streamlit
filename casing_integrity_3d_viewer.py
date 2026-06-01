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
    "La app genera un tubular 3D aunque el archivo tenga R01-R24, ID01-ID24, ID11-ID12 o solo IDMN-IDAV-IDMX."
)


NULL_VALUES = [-999.25, -999.2500, -999, -999.0]


RANGOS_ESTADO = pd.DataFrame(
    [
        {"Estado": "Colapso Crítico", "Rango": "ID -40% a -100%", "Interpretación": "Reducción extrema del diámetro interno."},
        {"Estado": "Colapso Severo", "Rango": "ID -20% a -40%", "Interpretación": "Reducción severa del diámetro interno."},
        {"Estado": "Colapso Moderado", "Rango": "ID -10% a -20%", "Interpretación": "Reducción moderada del diámetro interno."},
        {"Estado": "Colapso Leve", "Rango": "ID -0% a -10%", "Interpretación": "Reducción leve del diámetro interno."},
        {"Estado": "Buen estado", "Rango": "Cercano al ID nominal", "Interpretación": "Sin desviación relevante frente al ID nominal."},
        {"Estado": "Desgaste Leve", "Rango": "ID +0% a +10%", "Interpretación": "Aumento leve del diámetro interno."},
        {"Estado": "Desgaste Moderado", "Rango": "ID +10% a +20%", "Interpretación": "Aumento moderado del diámetro interno."},
        {"Estado": "Desgaste Severo", "Rango": "ID +20% a +40%", "Interpretación": "Aumento severo del diámetro interno."},
        {"Estado": "Desgaste Crítico", "Rango": "ID +40% a +100%", "Interpretación": "Aumento extremo del diámetro interno."},
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


def clasificar_signed_pct(valor, tolerancia):
    if abs(valor) <= tolerancia:
        return "Buen estado"

    if valor < 0:
        pct = abs(valor)

        if pct >= 40:
            return "Colapso Crítico"
        if pct >= 20:
            return "Colapso Severo"
        if pct >= 10:
            return "Colapso Moderado"

        return "Colapso Leve"

    pct = abs(valor)

    if pct >= 40:
        return "Desgaste Crítico"
    if pct >= 20:
        return "Desgaste Severo"
    if pct >= 10:
        return "Desgaste Moderado"

    return "Desgaste Leve"


def tipo_signed(valor, tolerancia):
    if abs(valor) <= tolerancia:
        return "Buen estado"

    if valor < 0:
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


def detectar_columnas_r(df):
    cols = []

    for i in range(1, 25):
        col = buscar_columna(df.columns, [f"R{i:02d}", f"R{i}"])

        if col:
            cols.append((f"R{i:02d}", col))

    return cols


def detectar_columnas_id_arm(df):
    cols = []

    for i in range(1, 25):
        col = buscar_columna(df.columns, [f"ID{i:02d}", f"ID{i}"])

        if col:
            cols.append((f"ID{i:02d}", col))

    return cols


def detectar_si_r_es_radio(data, r_cols, nominal_id):
    if not r_cols:
        return True

    valores = data[r_cols].to_numpy(dtype=float)
    mediana = np.nanmedian(valores)

    if not np.isfinite(mediana):
        return True

    return mediana <= nominal_id * 0.75


def crear_texto_valores_brazos(row, info):
    etiquetas = info["arm_labels"]
    value_cols = info["arm_value_cols"]

    if not etiquetas or not value_cols:
        return "Brazos: N/D"

    partes = []

    for etiqueta, col in zip(etiquetas, value_cols):
        if col in row.index:
            partes.append(f"{etiqueta}: {fmt(row[col], 3, ' in')}")
        else:
            partes.append(f"{etiqueta}: N/D")

    lineas = []

    for i in range(0, len(partes), 6):
        lineas.append(" | ".join(partes[i:i + 6]))

    return "<br>".join(lineas)


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
    col_id11 = buscar_columna(df.columns, ["ID11"])
    col_id12 = buscar_columna(df.columns, ["ID12"])

    data["eccentricity_in"] = limpiar_numero(df[col_ecc]) if col_ecc else np.nan
    data["ovality_las_in"] = limpiar_numero(df[col_oval_las]) if col_oval_las else np.nan
    data["id11_in"] = limpiar_numero(df[col_id11]) if col_id11 else np.nan
    data["id12_in"] = limpiar_numero(df[col_id12]) if col_id12 else np.nan

    r_cols_detectadas = detectar_columnas_r(df)
    id_cols_detectadas = detectar_columnas_id_arm(df)

    r_original_cols = []
    id_arm_cols = []

    for etiqueta, col in r_cols_detectadas:
        nuevo = f"{etiqueta}_in"
        data[nuevo] = limpiar_numero(df[col])
        r_original_cols.append(nuevo)

    for etiqueta, col in id_cols_detectadas:
        nuevo = f"{etiqueta}_in"
        data[nuevo] = limpiar_numero(df[col])
        id_arm_cols.append(nuevo)

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

    data["indice_color_pct"] = np.where(
        data["colapso_id_pct"] > data["desgaste_id_pct"],
        -data["colapso_id_pct"],
        data["desgaste_id_pct"]
    )

    data["indice_color_pct"] = np.where(
        np.abs(data["indice_color_pct"]) <= tolerancia_buen_estado,
        0,
        data["indice_color_pct"]
    )

    data["indice_color_pct"] = data["indice_color_pct"].clip(lower=-100, upper=100)

    data["estado_casing"] = data["indice_color_pct"].apply(
        lambda x: clasificar_signed_pct(x, tolerancia_buen_estado)
    )

    data["tipo_dominante"] = data["indice_color_pct"].apply(
        lambda x: tipo_signed(x, tolerancia_buen_estado)
    )

    data["remaining_wall_raw_in"] = (data["case_od_in"] - data["id_max_in"]) / 2
    data["remaining_wall_in"] = data["remaining_wall_raw_in"].clip(lower=0)

    data["integrity_raw_pct"] = 100 * data["remaining_wall_raw_in"] / data["nominal_wall_in"]
    data["integrity_pct"] = data["integrity_raw_pct"].clip(lower=0, upper=100)

    data["metal_loss_wall_pct"] = 100 - data["integrity_pct"]
    data["metal_loss_wall_pct"] = data["metal_loss_wall_pct"].clip(lower=0, upper=100)

    data["diameter_spread_in"] = data["id_max_in"] - data["id_min_in"]
    data["ovality_calc_in"] = data["diameter_spread_in"].clip(lower=0)

    data["out_of_physical_range"] = data["id_max_in"] > data["case_od_in"]

    info = {
        "r_original_cols": r_original_cols,
        "id_arm_cols": id_arm_cols,
        "arm_value_cols": [],
        "arm_diam_cols": [],
        "arm_labels": [],
        "modo_geometria": "",
    }

    if len(r_original_cols) >= 6:
        r_es_radio = detectar_si_r_es_radio(data, r_original_cols, nominal_id)

        info["modo_geometria"] = "R01 a R24" + (" como radio" if r_es_radio else " como diámetro")

        for col in r_original_cols:
            etiqueta = col.replace("_in", "")
            diam_col = f"D_{etiqueta}_in"

            if r_es_radio:
                data[diam_col] = data[col] * 2.0
            else:
                data[diam_col] = data[col]

            info["arm_value_cols"].append(col)
            info["arm_diam_cols"].append(diam_col)
            info["arm_labels"].append(etiqueta)

    elif len(id_arm_cols) >= 6:
        info["modo_geometria"] = "ID01 a ID24 como diámetro"

        for col in id_arm_cols:
            etiqueta = col.replace("_in", "")
            diam_col = f"D_{etiqueta}_in"

            data[diam_col] = data[col]

            info["arm_value_cols"].append(col)
            info["arm_diam_cols"].append(diam_col)
            info["arm_labels"].append(etiqueta)

    elif "id11_in" in data.columns and "id12_in" in data.columns and data["id11_in"].notna().any() and data["id12_in"].notna().any():
        info["modo_geometria"] = "Elipse suave con ID11 e ID12"

    else:
        info["modo_geometria"] = "Elipse suave con IDMN e IDMX"

    return data, info


def obtener_geometria(data, info, puntos_circunferencia):
    depth = data["depth_ft"].to_numpy()

    if len(info["arm_diam_cols"]) >= 6:
        diametros = data[info["arm_diam_cols"]].astype(float)
        diametros = diametros.interpolate(limit_direction="both")
        diametros = diametros.fillna(data["nominal_id_in"].iloc[0])
        diametros = diametros.to_numpy(dtype=float)

        radios = diametros / 2.0

        theta = np.linspace(0, 2 * np.pi, len(info["arm_diam_cols"]), endpoint=False)
        etiquetas = info["arm_labels"]

    else:
        theta = np.linspace(0, 2 * np.pi, puntos_circunferencia, endpoint=False)

        if info["modo_geometria"] == "Elipse suave con ID11 e ID12":
            d1 = data["id11_in"].fillna(data["id_avg_in"]).to_numpy(dtype=float)
            d2 = data["id12_in"].fillna(data["id_avg_in"]).to_numpy(dtype=float)

            rx = d1 / 2.0
            ry = d2 / 2.0

        else:
            rx = data["id_max_in"].fillna(data["id_avg_in"]).to_numpy(dtype=float) / 2.0
            ry = data["id_min_in"].fillna(data["id_avg_in"]).to_numpy(dtype=float) / 2.0

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
        diametros = radios * 2.0
        etiquetas = [f"P{i + 1:02d}" for i in range(radios.shape[1])]

    theta_cerrado = np.append(theta, 2 * np.pi)
    radios_cerrados = np.column_stack([radios, radios[:, 0]])

    theta_grid, depth_grid = np.meshgrid(theta_cerrado, depth)

    x = radios_cerrados * np.cos(theta_grid)
    y = radios_cerrados * np.sin(theta_grid)
    z = depth_grid

    return x, y, z, theta, radios, diametros, etiquetas


def matriz_color_3d(data, diametros, tolerancia):
    nominal = data["nominal_id_in"].to_numpy().reshape(-1, 1)

    indice = (diametros - nominal) / nominal * 100
    indice = np.clip(indice, -100, 100)

    indice = np.where(
        np.abs(indice) <= tolerancia,
        0,
        indice
    )

    return indice


def texto_hover_punto(row, etiqueta, valor_original, diametro, indice, info):
    estado = clasificar_signed_pct(indice, 0.0)

    texto = (
        f"<b>Lectura del casing</b><br>"
        f"MD: {fmt(row['depth_ft'], 2, ' ft')}<br>"
        f"Modo geometría: {info['modo_geometria']}<br>"
        f"Punto/Brazo: {etiqueta}<br>"
        f"Valor original: {fmt(valor_original, 3, ' in')}<br>"
        f"Diámetro equivalente: {fmt(diametro, 3, ' in')}<br>"
        f"Estado punto: {estado}<br>"
        f"Índice punto vs ID nominal: {fmt(indice, 2, ' %')}<br>"
        f"Estado fila: {row['estado_casing']}<br>"
        f"Tipo dominante fila: {row['tipo_dominante']}<br>"
        f"ID nominal: {fmt(row['nominal_id_in'], 3, ' in')}<br>"
        f"IDMN: {fmt(row['id_min_in'], 3, ' in')}<br>"
        f"IDAV: {fmt(row['id_avg_in'], 3, ' in')}<br>"
        f"IDMX: {fmt(row['id_max_in'], 3, ' in')}<br>"
        f"ID11: {fmt(row['id11_in'], 3, ' in')}<br>"
        f"ID12: {fmt(row['id12_in'], 3, ' in')}<br>"
        f"Desgaste respecto al ID: {fmt(row['desgaste_id_pct'], 2, ' %')}<br>"
        f"Colapso respecto al ID: {fmt(row['colapso_id_pct'], 2, ' %')}<br>"
        f"Ovalidad calculada: {fmt(row['ovality_calc_in'], 3, ' in')}<br>"
        f"Espesor remanente por IDMX: {fmt(row['remaining_wall_in'], 3, ' in')}<br>"
        f"Integridad por pared: {fmt(row['integrity_pct'], 1, ' %')}<br><br>"
        f"<b>Valores detectados:</b><br>"
        f"{crear_texto_valores_brazos(row, info)}"
    )

    return texto


def grafico_3d(data, info, max_points, puntos_circunferencia, tolerancia_buen_estado):
    if len(data) > max_points:
        indices = np.linspace(0, len(data) - 1, max_points).astype(int)
        data_plot = data.iloc[indices].copy()
    else:
        data_plot = data.copy()

    x, y, z, theta, radios, diametros, etiquetas = obtener_geometria(
        data_plot,
        info,
        puntos_circunferencia
    )

    indice_color = matriz_color_3d(data_plot, diametros, tolerancia_buen_estado)
    indice_cerrado = np.column_stack([indice_color, indice_color[:, 0]])

    fig = go.Figure()

    fig.add_trace(
        go.Surface(
            x=x,
            y=y,
            z=z,
            surfacecolor=indice_cerrado,
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

    x_hover = []
    y_hover = []
    z_hover = []
    color_hover = []
    text_hover = []

    for i in range(len(data_plot)):
        row = data_plot.iloc[i]

        for j in range(radios.shape[1]):
            x_hover.append(radios[i, j] * np.cos(theta[j]))
            y_hover.append(radios[i, j] * np.sin(theta[j]))
            z_hover.append(row["depth_ft"])
            color_hover.append(indice_color[i, j])

            etiqueta = etiquetas[j] if j < len(etiquetas) else f"P{j + 1:02d}"

            if len(info["arm_value_cols"]) >= 6 and j < len(info["arm_value_cols"]):
                valor_original = row[info["arm_value_cols"][j]]
            else:
                valor_original = diametros[i, j]

            text_hover.append(
                texto_hover_punto(
                    row,
                    etiqueta,
                    valor_original,
                    diametros[i, j],
                    indice_color[i, j],
                    info
                )
            )

    fig.add_trace(
        go.Scatter3d(
            x=x_hover,
            y=y_hover,
            z=z_hover,
            mode="markers",
            marker=dict(
                size=5,
                color=color_hover,
                colorscale=COLOR_SCALE_ESTADO,
                cmin=-100,
                cmax=100,
                opacity=0.35
            ),
            hovertext=text_hover,
            hovertemplate="%{hovertext}<extra></extra>",
            hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
            name="Lectura sobre casing"
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
        height=820,
        scene=dict(
            xaxis_title="X, in",
            yaxis_title="Y, in",
            zaxis_title="MD, ft",
            zaxis=dict(autorange="reversed"),
            aspectmode="manual",
            aspectratio=dict(x=1, y=1, z=4),
        ),
        margin=dict(l=0, r=0, t=90, b=0),
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
        ("id11_in", "ID11"),
        ("id12_in", "ID12"),
    ]:
        if col in data.columns and data[col].notna().any():
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

puntos_circunferencia = st.sidebar.slider(
    "Puntos de circunferencia si no hay R01-R24",
    24,
    144,
    96,
    12
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
    data, info = procesar_datos(
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


st.success(f"Modo de geometría usado: {info['modo_geometria']}")


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
    "Para EA9423 debe salir como tubo/elipse suave, no como triángulo. "
    "Pasa el cursor sobre los puntos del casing para ver la lectura."
)

st.plotly_chart(
    grafico_3d(
        data_filtrada,
        info,
        max_points,
        puntos_circunferencia,
        tolerancia_buen_estado
    ),
    use_container_width=True
)


st.subheader("Track de estado del casing")
st.plotly_chart(grafico_estado(data_filtrada), use_container_width=True)


st.subheader("Tracks IDMN, IDAV, IDMX, ID11 e ID12")
st.plotly_chart(grafico_id(data_filtrada), use_container_width=True)


st.subheader("Profundidades críticas reales")

md_min_critico = st.number_input(
    "MD mínimo para ranking crítico, ft",
    value=max(0.0, float(data_filtrada["depth_ft"].min())),
    step=10.0,
    format="%.1f"
)

md_max_critico = st.number_input(
    "MD máximo para ranking crítico, ft",
    value=float(data_filtrada["depth_ft"].max()),
    step=10.0,
    format="%.1f"
)

data_critica = data_filtrada[
    (data_filtrada["depth_ft"] >= md_min_critico) &
    (data_filtrada["depth_ft"] <= md_max_critico)
].copy()

columnas_criticas = [
    "depth_ft",
    "estado_casing",
    "tipo_dominante",
    "indice_color_pct",
    "desgaste_id_pct",
    "colapso_id_pct",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "id11_in",
    "id12_in",
    "desgaste_id_in",
    "colapso_id_in",
    "ovality_calc_in",
    "remaining_wall_in",
    "integrity_pct",
    "metal_loss_wall_pct",
    "out_of_physical_range"
]

columnas_criticas = [col for col in columnas_criticas if col in data_critica.columns]

if data_critica.empty:
    st.warning("No hay datos dentro del rango seleccionado.")
else:
    st.markdown("### Mayor desgaste")
    desgaste_top = data_critica[
        data_critica["desgaste_id_pct"] > tolerancia_buen_estado
    ].sort_values(
        ["desgaste_id_pct", "id_max_in"],
        ascending=[False, False]
    ).head(30)

    if desgaste_top.empty:
        st.success("No se detectó desgaste relevante dentro del rango seleccionado.")
    else:
        st.dataframe(desgaste_top[columnas_criticas].round(4), use_container_width=True)

    st.markdown("### Mayor colapso o reducción de diámetro")
    colapso_top = data_critica[
        data_critica["colapso_id_pct"] > tolerancia_buen_estado
    ].sort_values(
        ["colapso_id_pct", "id_min_in"],
        ascending=[False, True]
    ).head(30)

    if colapso_top.empty:
        st.success("No se detectó colapso relevante dentro del rango seleccionado.")
    else:
        st.dataframe(colapso_top[columnas_criticas].round(4), use_container_width=True)


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
    "id11_in",
    "id12_in",
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

columnas_salida = [col for col in columnas_salida if col in data_filtrada.columns]

st.dataframe(data_filtrada[columnas_salida].round(4), use_container_width=True)


csv = data_filtrada[columnas_salida].to_csv(index=False).encode("utf-8")

st.download_button(
    "Descargar tabla procesada CSV",
    data=csv,
    file_name="casing_integrity_universal_viewer.csv",
    mime="text/csv"
)
