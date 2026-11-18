import re
import unicodedata
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_FOLDER = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_FOLDER / "data" / "ventas.csv"
OUTPUT_FILE = PROJECT_FOLDER / "submission" / "ventas.csv"

COLUMNS = {
    "supplier id": "supplier_id",
    "supplier": "supplier",
    "country": "country",
    "city": "city",
    "purchase date": "purchase_date",
    "amount": "amount",
    "discount": "discount",
    "weight": "weight",
    "units": "units",
    "unit price": "unit_price",
    "contact email": "contact_email",
}

CITIES = {
    "bogota": "Bogotá",
    "medellin": "Medellín",
    "sopo": "Sopó",
    "tenjo": "Tenjo",
}

MISSING = {"", "N/A", "SIN CORREO"}


def remove_accents(text):
    """Quita las tildes de un texto."""
    text = unicodedata.normalize("NFKD", text)
    return "".join(char for char in text if not unicodedata.combining(char))


def load_data(input_file):
    """Lee el archivo crudo como texto y normaliza los encabezados."""
    sales = pd.read_csv(
        input_file,
        dtype=str,
        keep_default_na=False,
        encoding="utf-8-sig",
    )
    sales.columns = [COLUMNS[column.strip().lower()] for column in sales.columns]
    sales = sales.apply(lambda column: column.str.strip())
    return sales.mask(sales.apply(lambda column: column.str.upper().isin(MISSING)))


def clean_supplier(name):
    """Unifica mayúsculas, espacios y sufijos societarios del proveedor."""
    name = remove_accents(name).upper()
    name = re.sub(r"\s+", " ", name)
    name = re.sub(r"\bS\.?A\.?S\.?$", "S.A.S.", name)
    name = re.sub(r"\bS\.?A\.?$", "S.A.", name)
    name = re.sub(r"\bLTDA\.?$", "LTDA.", name)
    name = re.sub(r"\bINC\.?$", "INC.", name)
    return name


def clean_city(city):
    """Asigna el nombre oficial de la ciudad."""
    return CITIES[remove_accents(city).lower()]


def clean_date(date):
    """Convierte las distintas notaciones de fecha a AAAA-MM-DD.

    En las fechas con barra se asume día/mes (formato colombiano), salvo
    cuando el segundo número es mayor que 12 y solo puede ser el día.
    """
    parts = [int(part) for part in re.split(r"[/.\-]", date)]

    if parts[0] > 31:
        year, month, day = parts
    else:
        day, month, year = parts
        if "/" in date and month > 12:
            day, month = month, day
        if year < 100:
            year += 2000

    return f"{year:04d}-{month:02d}-{day:02d}"


def parse_number(text):
    """Convierte un valor monetario con separadores mixtos a número."""
    if pd.isna(text):
        return np.nan

    text = text.upper().replace("COP", "").replace("$", "").replace(" ", "")

    multiplier = 1
    if text.endswith("K"):
        multiplier = 1000
        text = text[:-1]

    text = text.replace(",", "")
    if text.count(".") > 1 or re.fullmatch(r"\d{1,3}\.\d{3}", text):
        integer, _, decimals = text.rpartition(".")
        if len(decimals) == 3:
            integer, decimals = text, ""
        text = integer.replace(".", "") + ("." + decimals if decimals else "")

    return float(text) * multiplier


def clean_discount(discount):
    """Expresa el descuento como proporción entre 0 y 1."""
    if pd.isna(discount):
        return np.nan

    value = float(discount.rstrip("%").strip())
    if discount.endswith("%") or value > 1:
        value /= 100
    return value


def clean_weight(weight):
    """Convierte el peso a kilogramos; sin unidad se asume kg."""
    if pd.isna(weight):
        return np.nan

    match = re.fullmatch(r"([\d.,]+)\s*(g|kg|ton)?", weight.lower())
    value = float(match.group(1).replace(",", "."))
    factor = {"g": 0.001, "kg": 1, "ton": 1000, None: 1}[match.group(2)]
    return round(value * factor, 3)


def fix_amounts(sales):
    """Repara montos, unidades y precios usando amount = units * unit_price."""
    sales["unit_price"] = sales["unit_price"].abs()

    expected = sales["units"] * sales["unit_price"]
    sales["amount"] = expected.where(expected.notna(), sales["amount"])

    missing_units = sales["units"].isna()
    sales.loc[missing_units, "units"] = (
        sales.loc[missing_units, "amount"] / sales.loc[missing_units, "unit_price"]
    ).round()

    return sales


def clean_sales(sales):
    """Aplica todas las reglas de limpieza al dataframe crudo."""
    sales["supplier_id"] = sales["supplier_id"].astype(int)
    sales["supplier"] = sales["supplier"].map(clean_supplier)
    sales["country"] = "COL"
    sales["city"] = sales["city"].map(clean_city)
    sales["purchase_date"] = sales["purchase_date"].map(clean_date)
    sales["amount"] = sales["amount"].map(parse_number)
    sales["discount"] = sales["discount"].map(clean_discount)
    sales["weight"] = sales["weight"].map(clean_weight)
    sales["units"] = pd.to_numeric(sales["units"])
    sales["unit_price"] = sales["unit_price"].map(parse_number)
    sales["contact_email"] = sales["contact_email"].str.lower()

    sales = fix_amounts(sales)
    sales["units"] = sales["units"].astype("Int64")

    return sales.drop_duplicates().sort_values("supplier_id").reset_index(drop=True)


def main():
    sales = load_data(INPUT_FILE)
    sales = clean_sales(sales)
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    sales.to_csv(OUTPUT_FILE, index=False)


if __name__ == "__main__":
    main()
