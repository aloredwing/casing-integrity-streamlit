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
    "La app clasifica colapso/desgaste por ID nominal y detecta variaciones locales por R01 a R24."
)


NULL_VALUES = [-999.25, -999.2500, -999, -999.0]


RANGOS_ESTADO = pd.DataFrame(
    [
        {
            "Estado": "Colapso Crítico",
            "Rango respecto al ID nominal": "ID - 40% a -100%",
            "Interpretación": "Reducción extrema del diámetro interno."
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
            "Interpretación": "Aumento extremo del diámetro interno."
        },
        {
            "Estado": "Variación local",
            "Rango respecto al patrón local": "Cambio brusco por brazo R01 a R24",
            "Interpretación": "Posible rotura, restricción puntual, suciedad, centralización o cambio local de lectura."
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


def tipo_dominante_signed(valor, tolerancia):
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
    r_cols = []

    for i in range(1, 25):
        col = buscar_columna(df.columns, [f"R{i:02d}", f"R{i}"])

        if col:
            r_cols.append((f"R{i:02d}", col))

    return r_cols


def detectar_columnas_id_arm(df):
    id_cols = []

    for i in range(1, 25):
        col = buscar_columna(df.columns, [f"ID{i:02d}", f"ID{i}"])

        if col:
            id_cols.append((f"ID{i:02d}", col))

    return id_cols


def detectar_si_r_es_radio(data, r_cols, nominal_id):
    if not r_cols:
        return True

    valores = data[r_cols].to_numpy(dtype=float)
    mediana = np.nanmedian(valores)

    if not np.isfinite(mediana):
        return True

    return mediana <= nominal_id * 0.75


def ventana_puntos_por_ft(depth, ventana_ft):
    d = pd.Series(depth).dropna().sort_values().to_numpy()

    if len(d) < 3:
        return 9

    paso = np.nanmedian(np.diff(d))

    if not np.isfinite(paso) or paso <= 0:
        paso = 0.125

    puntos = int(round(float(ventana_ft) / paso))
    puntos = max(7, puntos)

    if puntos % 2 == 0:
        puntos += 1

    return puntos


def calcular_variacion_local(
    data,
    arm_diam_cols,
    arm_labels,
    nominal_id,
    ventana_ft
):
    if not arm_diam_cols:
        data["local_variation_pct"] = 0.0
        data["local_variation_signed_pct"] = 0.0
        data["local_variation_delta_in"] = 0.0
        data["local_variation_arm"] = "N/D"
        data["local_variation_diameter_in"] = np.nan
        data["local_variation_baseline_in"] = np.nan
        return data, []

    ventana = ventana_puntos_por_ft(data["depth_ft"], ventana_ft)

    matriz = data[arm_diam_cols].astype(float)
    matriz = matriz.interpolate(limit_direction="both")

    base = matriz.rolling(
        window=ventana,
        center=True,
        min_periods=max(3, ventana // 3)
    ).median()

    base = base.bfill().ffill()

    delta = matriz - base
    delta_pct = delta / nominal_id * 100

    delta_pct_cols = []

    for col, label in zip(arm_diam_cols, arm_labels):
        nuevo = f"delta_local_{label}_pct"
        data[nuevo] = delta_pct[col]
        delta_pct_cols.append(nuevo)

        data[f"base_local_{label}_in"] = base[col]
        data[f"delta_local_{label}_in"] = delta[col]

    matriz_delta = delta_pct.to_numpy(dtype=float)
    matriz_abs = np.abs(matriz_delta)

    idx_max = np.nanargmax(matriz_abs, axis=1)

    signed = []
    abs_pct = []
    delta_in = []
    brazo = []
    diametro = []
    baseline = []

    matriz_diam = matriz.to_numpy(dtype=float)
    matriz_base = base.to_numpy(dtype=float)
    matriz_delta_in = delta.to_numpy(dtype=float)

    for i in range(len(data)):
        j = int(idx_max[i])

        signed.append(matriz_delta[i, j])
        abs_pct.append(abs(matriz_delta[i, j]))
        delta_in.append(matriz_delta_in[i, j])
        brazo.append(arm_labels[j])
        diametro.append(matriz_diam[i, j])
        baseline.append(matriz_base[i, j])

    data["local_variation_pct"] = abs_pct
    data["local_variation_signed_pct"] = signed
    data["local_variation_delta_in"] = delta_in
    data["local_variation_arm"] = brazo
    data["local_variation_diameter_in"] = diametro
    data["local_variation_baseline_in"] = baseline

    return data, delta_pct_cols


def procesar_datos(
    df,
    col_depth,
    col_idmn,
    col_idav,
    col_idmx,
    case_od,
    nominal_id,
    wall_thickness,
    tolerancia_buen_estado,
    ventana_variacion_ft,
    umbral_variacion_local_pct,
    usar_intervalo_manual,
    manual_from_ft,
    manual_to_ft,
    manual_score_pct
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

    r_original_cols = []
    r_las_cols = detectar_columnas_r(df)

    for etiqueta, col in r_las_cols:
        nuevo = f"{etiqueta}_in"
        data[nuevo] = limpiar_numero(df[col])
        r_original_cols.append(nuevo)

    id_arm_cols = []
    id_las_cols = detectar_columnas_id_arm(df)

    for etiqueta, col in id_las_cols:
        nuevo = f"{etiqueta}_in"
        data[nuevo] = limpiar_numero(df[col])
        id_arm_cols.append(nuevo)

    data = data.dropna(subset=["depth_ft", "id_min_in", "id_avg_in", "id_max_in"])
    data = data.sort_values("depth_ft").reset_index(drop=True)

    r_es_radio = detectar_si_r_es_radio(data, r_original_cols, nominal_id)

    arm_diam_cols = []
    arm_value_cols = []
    arm_labels = []
    modo_brazos = "aproximado por IDMN/IDMX"

    if r_original_cols:
        modo_brazos = "R01 a R24 como radio" if r_es_radio else "R01 a R24 como diámetro"

        for col in r_original_cols:
            label = col.replace("_in", "")
            nuevo = f"D_{label}_in"

            if r_es_radio:
                data[nuevo] = data[col] * 2.0
            else:
                data[nuevo] = data[col]

            arm_diam_cols.append(nuevo)
            arm_value_cols.append(col)
            arm_labels.append(label)

    elif id_arm_cols:
        modo_brazos = "ID01 a ID24 como diámetro"

        for col in id_arm_cols:
            label = col.replace("_in", "")
            nuevo = f"D_{label}_in"
            data[nuevo] = data[col]

            arm_diam_cols.append(nuevo)
            arm_value_cols.append(col)
            arm_labels.append(label)

    data["desgaste_id_in"] = data["id_max_in"] - data["nominal_id_in"]
    data["colapso_id_in"] = data["nominal_id_in"] - data["id_min_in"]

    data["desgaste_id_pct"] = (
        data["desgaste_id_in"].clip(lower=0) / data["nominal_id_in"] * 100
    ).clip(lower=0, upper=100)

    data["colapso_id_pct"] = (
        data["colapso_id_in"].clip(lower=0) / data["nominal_id_in"] * 100
    ).clip(lower=0, upper=100)

    if arm_diam_cols:
        arm_matrix = data[arm_diam_cols].astype(float)
        arm_matrix = arm_matrix.fillna(nominal_id)

        signed_matrix = (arm_matrix.to_numpy(dtype=float) - nominal_id) / nominal_id * 100
        signed_matrix = np.clip(signed_matrix, -100, 100)

        idx_worst = np.nanargmax(np.abs(signed_matrix), axis=1)
        worst_signed = signed_matrix[np.arange(len(data)), idx_worst]

        data["worst_arm"] = [arm_labels[int(j)] for j in idx_worst]
        data["worst_arm_signed_pct"] = worst_signed
    else:
        signed_base = np.where(
            data["colapso_id_pct"] > data["desgaste_id_pct"],
            -data["colapso_id_pct"],
            data["desgaste_id_pct"]
        )

        data["worst_arm"] = "IDMN/IDMX"
        data["worst_arm_signed_pct"] = signed_base

    data["indice_base_pct"] = np.where(
        np.abs(data["worst_arm_signed_pct"]) <= tolerancia_buen_estado,
        0,
        data["worst_arm_signed_pct"]
    )

    data, delta_pct_cols = calcular_variacion_local(
        data,
        arm_diam_cols,
        arm_labels,
        nominal_id,
        ventana_variacion_ft
    )

    data["variacion_local_alerta"] = data["local_variation_pct"] >= umbral_variacion_local_pct

    data["indice_variacion_visual_pct"] = np.where(
        data["variacion_local_alerta"],
        np.sign(data["local_variation_signed_pct"]) * np.maximum(
            data["local_variation_pct"],
            10
        ),
        0
    )

    if usar_intervalo_manual:
        desde = min(manual_from_ft, manual_to_ft)
        hasta = max(manual_from_ft, manual_to_ft)

        data["intervalo_visual_pct"] = np.where(
            (data["depth_ft"] >= desde) & (data["depth_ft"] <= hasta),
            manual_score_pct,
            0
        )
    else:
        data["intervalo_visual_pct"] = 0.0

    data["indice_color_pct"] = data["indice_base_pct"]

    data["indice_color_pct"] = np.where(
        np.abs(data["indice_variacion_visual_pct"]) > np.abs(data["indice_color_pct"]),
        data["indice_variacion_visual_pct"],
        data["indice_color_pct"]
    )

    data["indice_color_pct"] = np.where(
        data["intervalo_visual_pct"] > np.abs(data["indice_color_pct"]),
        data["intervalo_visual_pct"],
        data["indice_color_pct"]
    )

    data["indice_color_pct"] = data["indice_color_pct"].clip(lower=-100, upper=100)

    data["estado_casing"] = data["indice_color_pct"].apply(
        lambda x: clasificar_signed_pct(x, tolerancia_buen_estado)
    )

    data["tipo_dominante"] = data["indice_color_pct"].apply(
        lambda x: tipo_dominante_signed(x, tolerancia_buen_estado)
    )

    data.loc[data["variacion_local_alerta"], "tipo_dominante"] = "Variación local por brazo"
    data.loc[data["intervalo_visual_pct"] > 0, "tipo_dominante"] = "Intervalo visual marcado"

    data["remaining_wall_raw_in"] = (data["case_od_in"] - data["id_max_in"]) / 2
    data["remaining_wall_in"] = data["remaining_wall_raw_in"].clip(lower=0)

    data["integrity_raw_pct"] = 100 * data["remaining_wall_raw_in"] / data["nominal_wall_in"]
    data["integrity_pct"] = data["integrity_raw_pct"].clip(lower=0, upper=100)

    data["metal_loss_wall_pct"] = 100 - data["integrity_pct"]
    data["metal_loss_wall_pct"] = data["metal_loss_wall_pct"].clip(lower=0, upper=100)

    data["diameter_spread_in"] = data["id_max_in"] - data["id_min_in"]
    data["ovality_calc_in"] = data["diameter_spread_in"].clip(lower=0)

    data["out_of_physical_range"] = data["id_max_in"] > data["case_od_in"]

    info_brazos = {
        "r_original_cols": r_original_cols,
        "id_arm_cols": id_arm_cols,
        "arm_diam_cols": arm_diam_cols,
        "arm_value_cols": arm_value_cols,
        "arm_labels": arm_labels,
        "delta_pct_cols": delta_pct_cols,
        "modo_brazos": modo_brazos,
        "r_es_radio": r_es_radio
    }

    return data, info_brazos


def construir_lineas_r_hover(row, r_original_cols):
    if not r_original_cols:
        return "R01 a R24: N/D"

    partes = []

    for i in range(1, 25):
        col = f"R{i:02d}_in"

        if col in row.index:
            partes.append(f"R{i:02d}: {fmt(row[col], 3, ' in')}")
        else:
            partes.append(f"R{i:02d}: N/D")

    linea_1 = " | ".join(partes[0:6])
    linea_2 = " | ".join(partes[6:12])
    linea_3 = " | ".join(partes[12:18])
    linea_4 = " | ".join(partes[18:24])

    return (
        f"<b>Valores R01 a R24</b><br>"
        f"{linea_1}<br>"
        f"{linea_2}<br>"
        f"{linea_3}<br>"
        f"{linea_4}"
    )


def texto_hover_punto(row, etiqueta_brazo, valor_original, diametro_equiv, indice_punto, delta_local_pct, r_original_cols, modo_brazos):
    estado_punto = clasificar_signed_pct(indice_punto, 0.0)

    texto = (
        f"<b>Lectura del casing</b><br>"
        f"MD: {fmt(row['depth_ft'], 2, ' ft')}<br>"
        f"Brazo: {etiqueta_brazo}<br>"
        f"Modo brazos: {modo_brazos}<br>"
        f"Valor original brazo: {fmt(valor_original, 3, ' in')}<br>"
        f"Diámetro equivalente: {fmt(diametro_equiv, 3, ' in')}<br>"
        f"Estado punto: {estado_punto}<br>"
        f"Índice punto vs ID nominal: {fmt(indice_punto, 2, ' %')}<br>"
        f"Variación local del brazo: {fmt(delta_local_pct, 2, ' %')}<br>"
        f"Estado fila: {row['estado_casing']}<br>"
        f"Tipo dominante fila: {row['tipo_dominante']}<br>"
        f"Brazo más variable: {row['local_variation_arm']}<br>"
        f"Variación local máxima: {fmt(row['local_variation_pct'], 2, ' %')}<br>"
        f"Delta local máximo: {fmt(row['local_variation_delta_in'], 3, ' in')}<br>"
        f"ID nominal: {fmt(row['nominal_id_in'], 3, ' in')}<br>"
        f"IDMN: {fmt(row['id_min_in'], 3, ' in')}<br>"
        f"IDAV: {fmt(row['id_avg_in'], 3, ' in')}<br>"
        f"IDMX: {fmt(row['id_max_in'], 3, ' in')}<br>"
        f"Desgaste respecto al ID: {fmt(row['desgaste_id_pct'], 2, ' %')}<br>"
        f"Colapso respecto al ID: {fmt(row['colapso_id_pct'], 2, ' %')}<br>"
        f"Ovalidad calculada: {fmt(row['ovality_calc_in'], 3, ' in')}<br>"
        f"Espesor remanente por IDMX: {fmt(row['remaining_wall_in'], 3, ' in')}<br>"
        f"Integridad por pared: {fmt(row['integrity_pct'], 1, ' %')}<br><br>"
        f"{construir_lineas_r_hover(row, r_original_cols)}"
    )

    return texto


def obtener_geometria(data, info_brazos):
    arm_diam_cols = info_brazos["arm_diam_cols"]

    if arm_diam_cols:
        diametros = data[arm_diam_cols].astype(float)
        diametros = diametros.fillna(data["nominal_id_in"].iloc[0])
        diametros = diametros.to_numpy(dtype=float)
        radios = diametros / 2.0

        etiquetas = info_brazos["arm_labels"]
        theta = np.linspace(0, 2 * np.pi, len(arm_diam_cols), endpoint=False)

    else:
        theta = np.linspace(0, 2 * np.pi, 96)

        rx = data["id_max_in"].fillna(data["id_avg_in"]).to_numpy() / 2
        ry = data["id_min_in"].fillna(data["id_avg_in"]).to_numpy() / 2

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
        diametros = radios * 2
        etiquetas = [f"P{i + 1:02d}" for i in range(radios.shape[1])]

    theta_cerrado = np.append(theta, 2 * np.pi)
    radios_cerrados = np.column_stack([radios, radios[:, 0]])

    depth = data["depth_ft"].to_numpy()
    theta_grid, depth_grid = np.meshgrid(theta_cerrado, depth)

    x = radios_cerrados * np.cos(theta_grid)
    y = radios_cerrados * np.sin(theta_grid)
    z = depth_grid

    return x, y, z, theta, radios, diametros, etiquetas


def matriz_color_3d(data, diametros, info_brazos, tolerancia):
    nominal = data["nominal_id_in"].to_numpy().reshape(-1, 1)

    indice = (diametros - nominal) / nominal * 100
    indice = np.clip(indice, -100, 100)

    indice = np.where(
        np.abs(indice) <= tolerancia,
        0,
        indice
    )

    delta_cols = info_brazos["delta_pct_cols"]

    if delta_cols and len(delta_cols) == indice.shape[1]:
        delta = data[delta_cols].to_numpy(dtype=float)
        alerta = np.abs(delta) >= data["umbral_variacion_local_pct"].iloc[0]

        refuerzo = np.sign(delta) * np.maximum(np.abs(delta), 10)

        indice = np.where(
            alerta & (np.abs(refuerzo) > np.abs(indice)),
            refuerzo,
            indice
        )

    if "intervalo_visual_pct" in data.columns:
        manual = data["intervalo_visual_pct"].to_numpy().reshape(-1, 1)

        indice = np.where(
            manual > np.abs(indice),
            manual,
            indice
        )

    return np.clip(indice, -100, 100)


def grafico_3d(data, info_brazos, max_points, tolerancia_buen_estado):
    if len(data) > max_points:
        indices = np.linspace(0, len(data) - 1, max_points).astype(int)
        data_plot = data.iloc[indices].copy()
    else:
        data_plot = data.copy()

    x, y, z, theta, radios, diametros, etiquetas = obtener_geometria(data_plot, info_brazos)

    indice_color = matriz_color_3d(
        data_plot,
        diametros,
        info_brazos,
        tolerancia_buen_estado
    )

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

    arm_value_cols = info_brazos["arm_value_cols"]
    r_original_cols = info_brazos["r_original_cols"]
    delta_cols = info_brazos["delta_pct_cols"]
    modo_brazos = info_brazos["modo_brazos"]

    for i in range(len(data_plot)):
        row = data_plot.iloc[i]

        for j in range(radios.shape[1]):
            x_hover.append(radios[i, j] * np.cos(theta[j]))
            y_hover.append(radios[i, j] * np.sin(theta[j]))
            z_hover.append(row["depth_ft"])
            color_hover.append(indice_color[i, j])

            etiqueta = etiquetas[j] if j < len(etiquetas) else f"P{j + 1:02d}"

            if arm_value_cols and j < len(arm_value_cols):
                valor_original = row[arm_value_cols[j]]
            else:
                valor_original = diametros[i, j]

            if delta_cols and j < len(delta_cols):
                delta_local_pct = row[delta_cols[j]]
            else:
                delta_local_pct = 0.0

            text_hover.append(
                texto_hover_punto(
                    row,
                    etiqueta,
                    valor_original,
                    diametros[i, j],
                    indice_color[i, j],
                    delta_local_pct,
                    r_original_cols,
                    modo_brazos
                )
            )

    fig.add_trace(
        go.Scatter3d(
            x=x_hover,
            y=y_hover,
            z=z_hover,
            mode="markers",
            marker=dict(
                size=6,
                color=color_hover,
                colorscale=COLOR_SCALE_ESTADO,
                cmin=-100,
                cmax=100,
                opacity=0.45
            ),
            hovertext=text_hover,
            hovertemplate="%{hovertext}<extra></extra>",
            hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
            name="Lectura R01 a R24",
            showlegend=True
        )
    )

    alertas = data_plot[data_plot["variacion_local_alerta"]].copy()

    if not alertas.empty and info_brazos["arm_labels"]:
        if len(alertas) > 200:
            alertas = alertas.sort_values("local_variation_pct", ascending=False).head(200)

        x_a = []
        y_a = []
        z_a = []
        c_a = []
        t_a = []

        for _, row in alertas.iterrows():
            brazo = row["local_variation_arm"]

            if brazo in info_brazos["arm_labels"]:
                j = info_brazos["arm_labels"].index(brazo)
            else:
                j = 0

            idx = data_plot.index.get_loc(row.name)

            x_a.append(radios[idx, j] * np.cos(theta[j]))
            y_a.append(radios[idx, j] * np.sin(theta[j]))
            z_a.append(row["depth_ft"])
            c_a.append(row["local_variation_signed_pct"])

            t_a.append(
                f"<b>Variación local detectada</b><br>"
                f"MD: {fmt(row['depth_ft'], 2, ' ft')}<br>"
                f"Brazo más variable: {row['local_variation_arm']}<br>"
                f"Variación local: {fmt(row['local_variation_pct'], 2, ' %')}<br>"
                f"Delta local: {fmt(row['local_variation_delta_in'], 3, ' in')}<br>"
                f"Diámetro actual: {fmt(row['local_variation_diameter_in'], 3, ' in')}<br>"
                f"Base local: {fmt(row['local_variation_baseline_in'], 3, ' in')}<br>"
                f"Estado fila: {row['estado_casing']}<br>"
                f"Tipo dominante: {row['tipo_dominante']}<br>"
                f"ID nominal: {fmt(row['nominal_id_in'], 3, ' in')}<br>"
                f"IDMN: {fmt(row['id_min_in'], 3, ' in')}<br>"
                f"IDMX: {fmt(row['id_max_in'], 3, ' in')}"
            )

        fig.add_trace(
            go.Scatter3d(
                x=x_a,
                y=y_a,
                z=z_a,
                mode="markers",
                marker=dict(
                    size=9,
                    color=c_a,
                    colorscale=COLOR_SCALE_ESTADO,
                    cmin=-100,
                    cmax=100,
                    symbol="diamond",
                    opacity=1.0
                ),
                hovertext=t_a,
                hovertemplate="%{hovertext}<extra></extra>",
                hoverlabel=dict(bgcolor="white", font_size=13, font_color="black"),
                name="Variación local detectada"
            )
        )

    fig.add_annotation(
        text=(
            "<b>Escala:</b> Colapso crítico ≤ -40% | Colapso severo -20% a -40% | "
            "Colapso moderado -10% a -20% | Colapso leve 0% a -10% | "
            "Buen estado ≈ ID nominal | Desgaste leve 0% a 10% | "
            "Desgaste moderado 10% a 20% | Desgaste severo 20% a 40% | "
            "Desgaste crítico ≥ 40% | Diamantes = variación local por brazo"
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
        height=840,
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

    fig.add_trace(
        go.Scatter(
            x=data["local_variation_signed_pct"],
            y=data["depth_ft"],
            mode="lines",
            name="Variación local firmada, %"
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
        height=580,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Desviación respecto al ID nominal / variación local, %", range=[-100, 100]),
        legend=dict(orientation="h"),
        margin=dict(l=20, r=20, t=50, b=20),
    )

    return fig


def grafico_variacion_local(data, umbral):
    fig = go.Figure()

    fig.add_trace(
        go.Scatter(
            x=data["local_variation_pct"],
            y=data["depth_ft"],
            mode="lines",
            name="Variación local máxima, %"
        )
    )

    fig.add_vline(
        x=umbral,
        line_dash="dash",
        annotation_text="Umbral variación local"
    )

    fig.update_layout(
        height=560,
        yaxis=dict(title="MD, ft", autorange="reversed"),
        xaxis=dict(title="Variación local por brazo, % del ID nominal", range=[0, max(10, data["local_variation_pct"].max() * 1.2)]),
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


def columnas_r_para_tabla(r_original_cols):
    return [col for col in [f"R{i:02d}_in" for i in range(1, 25)] if col in r_original_cols]


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


nombre_archivo = archivo.name.upper()
pozo_detectado = str(meta.get("pozo", "")).upper()
es_aa9891 = "AA9891" in nombre_archivo or "AA9891" in pozo_detectado


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

st.sidebar.header("Variación local por brazos R01 a R24")

ventana_variacion_ft = st.sidebar.number_input(
    "Ventana base local, ft",
    value=12.0,
    min_value=1.0,
    max_value=80.0,
    step=1.0,
    format="%.1f"
)

umbral_variacion_local_pct = st.sidebar.number_input(
    "Umbral variación local, % del ID",
    value=0.80,
    min_value=0.10,
    max_value=20.0,
    step=0.10,
    format="%.2f"
)

st.sidebar.header("Intervalo visual manual")

usar_intervalo_manual = st.sidebar.checkbox(
    "Marcar intervalo visual en 3D",
    value=False
)

manual_from_ft = st.sidebar.number_input(
    "Desde, ft",
    value=350.0,
    step=1.0,
    format="%.1f"
)

manual_to_ft = st.sidebar.number_input(
    "Hasta, ft",
    value=360.0,
    step=1.0,
    format="%.1f"
)

manual_score_pct = st.sidebar.slider(
    "Intensidad visual del intervalo, %",
    0,
    100,
    85
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
    "El color principal compara el diámetro por brazo contra el ID nominal. "
    "Los diamantes del 3D marcan variaciones locales por brazo R01 a R24, que ayudan a detectar cambios puntuales como una posible rotura, "
    "aunque IDMN o IDMX no cambien de forma evidente en el track general."
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
    data, info_brazos = procesar_datos(
        df,
        col_depth,
        col_idmn,
        col_idav,
        col_idmx,
        case_od,
        nominal_id,
        wall_thickness,
        tolerancia_buen_estado,
        ventana_variacion_ft,
        umbral_variacion_local_pct,
        usar_intervalo_manual,
        manual_from_ft,
        manual_to_ft,
        manual_score_pct
    )
except Exception as e:
    st.error(f"No pude procesar los datos: {e}")
    st.stop()


if data.empty:
    st.error("No quedaron datos válidos después de limpiar el archivo.")
    st.stop()


data["umbral_variacion_local_pct"] = umbral_variacion_local_pct


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
k5.metric("Máx. variación local", f"{data_filtrada['local_variation_pct'].max():.2f} %")
k6.metric("Menor IDMN", f"{data_filtrada['id_min_in'].min():.3f} in")


if info_brazos["r_original_cols"]:
    st.success(
        f"Se detectaron {len(info_brazos['r_original_cols'])} columnas R. "
        f"Modo usado: {info_brazos['modo_brazos']}."
    )
elif info_brazos["id_arm_cols"]:
    st.warning(
        f"No se detectaron R01 a R24, pero sí {len(info_brazos['id_arm_cols'])} columnas ID por brazo. "
        f"Modo usado: {info_brazos['modo_brazos']}."
    )
else:
    st.warning(
        "No se detectaron columnas R01 a R24 ni ID01 a ID24. "
        "El 3D usará una geometría aproximada con IDMN e IDMX."
    )


fuera_rango = int(data_filtrada["out_of_physical_range"].sum())

if fuera_rango > 0:
    st.warning(
        f"Hay {fuera_rango} puntos donde IDMX supera el OD del casing. "
        "Estos puntos deben revisarse como lectura fuera de rango físico."
    )


st.subheader("Tubular 3D por estado del casing y variación local")
st.info(
    "Pasa el cursor sobre los puntos del casing. "
    "Los diamantes indican variación local detectada por brazo, útil para revisar posibles roturas o cambios puntuales."
)

st.plotly_chart(
    grafico_3d(
        data_filtrada,
        info_brazos,
        max_points,
        tolerancia_buen_estado
    ),
    use_container_width=True
)


st.subheader("Track de estado y variación local")
st.plotly_chart(grafico_estado(data_filtrada), use_container_width=True)


st.subheader("Track de variación local por brazo")
st.plotly_chart(grafico_variacion_local(data_filtrada, umbral_variacion_local_pct), use_container_width=True)


st.subheader("Tracks IDMN, IDAV e IDMX")
st.plotly_chart(grafico_id(data_filtrada), use_container_width=True)


st.subheader("Variaciones locales detectadas")

variaciones = data_filtrada[data_filtrada["variacion_local_alerta"]].copy()

columnas_variacion = [
    "depth_ft",
    "estado_casing",
    "tipo_dominante",
    "local_variation_arm",
    "local_variation_pct",
    "local_variation_signed_pct",
    "local_variation_delta_in",
    "local_variation_diameter_in",
    "local_variation_baseline_in",
    "indice_color_pct",
    "id_min_in",
    "id_avg_in",
    "id_max_in",
    "desgaste_id_pct",
    "colapso_id_pct",
    "ovality_calc_in"
]

if variaciones.empty:
    st.success("No se detectaron variaciones locales por encima del umbral seleccionado.")
else:
    st.dataframe(
        variaciones.sort_values("local_variation_pct", ascending=False)[columnas_variacion].head(80).round(4),
        use_container_width=True
    )


st.subheader("Profundidades más críticas")

top = data_filtrada.copy()
top["severidad_abs_pct"] = top["indice_color_pct"].abs()

top = top.sort_values(
    ["severidad_abs_pct", "local_variation_pct", "desgaste_id_pct", "colapso_id_pct"],
    ascending=[False, False, False, False]
).head(30)

columnas_top = [
    "depth_ft",
    "estado_casing",
    "tipo_dominante",
    "worst_arm",
    "indice_color_pct",
    "local_variation_arm",
    "local_variation_pct",
    "local_variation_delta_in",
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
        zona_350_450.sort_values(
            ["local_variation_pct", "severidad_abs_pct"],
            ascending=[False, False]
        )[columnas_top].head(100).round(4),
        use_container_width=True
    )


st.subheader("Lectura R01 a R24 por profundidad")

r_cols_tabla = columnas_r_para_tabla(info_brazos["r_original_cols"])

if r_cols_tabla:
    columnas_r_tabla = [
        "depth_ft",
        "estado_casing",
        "tipo_dominante",
        "local_variation_arm",
        "local_variation_pct",
        "indice_color_pct"
    ] + r_cols_tabla

    st.dataframe(data_filtrada[columnas_r_tabla].round(4), use_container_width=True)
else:
    st.info("El archivo cargado no contiene columnas R01 a R24.")


st.subheader("Tabla procesada completa")

columnas_salida = [
    "depth_ft",
    "estado_casing",
    "tipo_dominante",
    "worst_arm",
    "indice_color_pct",
    "indice_base_pct",
    "indice_variacion_visual_pct",
    "intervalo_visual_pct",
    "variacion_local_alerta",
    "local_variation_arm",
    "local_variation_pct",
    "local_variation_signed_pct",
    "local_variation_delta_in",
    "local_variation_diameter_in",
    "local_variation_baseline_in",
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

columnas_salida = columnas_salida + r_cols_tabla + info_brazos["delta_pct_cols"]

columnas_salida = [col for col in columnas_salida if col in data_filtrada.columns]

st.dataframe(data_filtrada[columnas_salida].round(4), use_container_width=True)


csv = data_filtrada[columnas_salida].to_csv(index=False).encode("utf-8")

st.download_button(
    "Descargar tabla procesada CSV",
    data=csv,
    file_name="casing_variacion_local_r01_r24.csv",
    mime="text/csv"
)
