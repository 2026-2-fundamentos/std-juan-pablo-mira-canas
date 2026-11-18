import csv
import sqlite3
from pathlib import Path

import pandas as pd


PROJECT_FOLDER = Path(__file__).resolve().parents[1]
INPUT_FILE = PROJECT_FOLDER / "data" / "ventas.csv"
OUTPUT_FILE = PROJECT_FOLDER / "submission" / "ventas.csv"

RAW_COLUMNS = [
    "supplier_id",
    "supplier",
    "country",
    "city",
    "purchase_date",
    "amount",
    "discount",
    "weight",
    "units",
    "unit_price",
    "contact_email",
]


def without_accents(expression):
    """Devuelve una expresión SQL que reemplaza las vocales con tilde."""
    for accented, plain in zip("ÁÉÍÓÚáéíóú", "AEIOUaeiou"):
        expression = f"REPLACE({expression}, '{accented}', '{plain}')"
    return expression


def as_number(expression):
    """Devuelve una expresión SQL que convierte un monto con separadores mixtos."""
    text = (
        f"REPLACE(REPLACE(REPLACE(REPLACE(UPPER({expression}), "
        f"'COP', ''), '$', ''), ' ', ''), ',', '')"
    )
    return f"""
        CASE
            WHEN {text} LIKE '%K'
                THEN CAST(SUBSTR({text}, 1, LENGTH({text}) - 1) AS REAL) * 1000
            WHEN {text} GLOB '*.[0-9][0-9]'
                THEN CAST(
                    REPLACE(SUBSTR({text}, 1, LENGTH({text}) - 3), '.', '')
                    || SUBSTR({text}, -3) AS REAL
                )
            ELSE CAST(REPLACE({text}, '.', '') AS REAL)
        END
    """


def missing_as_null(column):
    """Devuelve una expresión SQL que recorta el texto y marca los faltantes."""
    return f"""
        CASE
            WHEN UPPER(TRIM({column})) IN ('', 'N/A', 'SIN CORREO') THEN NULL
            ELSE TRIM({column})
        END AS {column}
    """


def load_raw_table(connection):
    """Carga el CSV crudo, todo como texto, en la tabla raw_sales."""
    with INPUT_FILE.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.reader(file)
        next(reader)
        rows = list(reader)

    columns = ", ".join(f"{column} TEXT" for column in RAW_COLUMNS)
    connection.execute(f"CREATE TABLE raw_sales ({columns})")
    connection.executemany(
        f"INSERT INTO raw_sales VALUES ({', '.join('?' * len(RAW_COLUMNS))})",
        rows,
    )


def create_trimmed_table(connection):
    """Recorta espacios y convierte '', 'N/A' y 'sin correo' en NULL."""
    columns = ",".join(missing_as_null(column) for column in RAW_COLUMNS)
    connection.execute(f"CREATE TABLE trimmed_sales AS SELECT {columns} FROM raw_sales")


def create_typed_table(connection):
    """Normaliza el texto y convierte cada columna a su tipo."""
    supplier = f"UPPER({without_accents('supplier')})"
    for _ in range(3):
        supplier = f"REPLACE({supplier}, '  ', ' ')"
    supplier = f"REPLACE({supplier}, '.', '')"

    city = f"LOWER({without_accents('city')})"

    connection.execute(
        f"""
        CREATE TABLE typed_sales AS
        WITH dates AS (
            SELECT
                rowid AS id,
                REPLACE(REPLACE(purchase_date, '.', '/'), '-', '/') AS date_text,
                purchase_date LIKE '%/%' AS uses_slash
            FROM trimmed_sales
        ),
        date_parts AS (
            SELECT
                id,
                uses_slash,
                CAST(SUBSTR(date_text, 1, INSTR(date_text, '/') - 1) AS INTEGER) AS p1,
                CAST(
                    SUBSTR(
                        SUBSTR(date_text, INSTR(date_text, '/') + 1),
                        1,
                        INSTR(SUBSTR(date_text, INSTR(date_text, '/') + 1), '/') - 1
                    ) AS INTEGER
                ) AS p2,
                CAST(
                    SUBSTR(
                        SUBSTR(date_text, INSTR(date_text, '/') + 1),
                        INSTR(SUBSTR(date_text, INSTR(date_text, '/') + 1), '/') + 1
                    ) AS INTEGER
                ) AS p3
            FROM dates
        ),
        clean_dates AS (
            -- Con barra se asume día/mes, salvo que el segundo número pase de 12.
            SELECT
                id,
                CASE
                    WHEN p1 > 31 THEN PRINTF('%04d-%02d-%02d', p1, p2, p3)
                    WHEN uses_slash AND p2 > 12
                        THEN PRINTF('%04d-%02d-%02d', p3, p1, p2)
                    ELSE PRINTF(
                        '%04d-%02d-%02d',
                        CASE WHEN p3 < 100 THEN p3 + 2000 ELSE p3 END,
                        p2,
                        p1
                    )
                END AS purchase_date
            FROM date_parts
        )
        SELECT
            CAST(s.supplier_id AS INTEGER) AS supplier_id,
            CASE
                WHEN {supplier} LIKE '% SAS'
                    THEN SUBSTR({supplier}, 1, LENGTH({supplier}) - 4) || ' S.A.S.'
                WHEN {supplier} LIKE '% SA'
                    THEN SUBSTR({supplier}, 1, LENGTH({supplier}) - 3) || ' S.A.'
                WHEN {supplier} LIKE '% LTDA'
                    THEN {supplier} || '.'
                WHEN {supplier} LIKE '% INC'
                    THEN {supplier} || '.'
                ELSE {supplier}
            END AS supplier,
            'COL' AS country,
            CASE {city}
                WHEN 'bogota' THEN 'Bogotá'
                WHEN 'medellin' THEN 'Medellín'
                WHEN 'sopo' THEN 'Sopó'
                WHEN 'tenjo' THEN 'Tenjo'
            END AS city,
            d.purchase_date,
            {as_number('s.amount')} AS amount,
            CASE
                WHEN s.discount LIKE '%\\%%' ESCAPE '\\'
                    THEN CAST(TRIM(REPLACE(s.discount, '%', '')) AS REAL) / 100
                WHEN CAST(s.discount AS REAL) > 1
                    THEN CAST(s.discount AS REAL) / 100
                ELSE CAST(s.discount AS REAL)
            END AS discount,
            -- Sin unidad se asume kg.
            ROUND(
                CAST(REPLACE(s.weight, ',', '.') AS REAL) * CASE
                    WHEN s.weight LIKE '%ton' THEN 1000
                    WHEN s.weight LIKE '%kg' THEN 1
                    WHEN s.weight LIKE '%g' THEN 0.001
                    ELSE 1
                END,
                3
            ) AS weight,
            CAST(s.units AS INTEGER) AS units,
            ABS({as_number('s.unit_price')}) AS unit_price,
            LOWER(s.contact_email) AS contact_email
        FROM trimmed_sales AS s
        JOIN clean_dates AS d ON d.id = s.rowid
        """
    )


def create_clean_table(connection):
    """Repara montos y unidades con amount = units * unit_price y quita duplicados."""
    connection.execute(
        """
        CREATE TABLE clean_sales AS
        SELECT DISTINCT
            supplier_id,
            supplier,
            country,
            city,
            purchase_date,
            COALESCE(units * unit_price, amount) AS amount,
            discount,
            weight,
            COALESCE(units, CAST(ROUND(amount / unit_price) AS INTEGER)) AS units,
            unit_price,
            contact_email
        FROM typed_sales
        ORDER BY supplier_id
        """
    )


def main():
    connection = sqlite3.connect(":memory:")

    load_raw_table(connection)
    create_trimmed_table(connection)
    create_typed_table(connection)
    create_clean_table(connection)

    sales = pd.read_sql("SELECT * FROM clean_sales", connection)
    sales["units"] = sales["units"].astype("Int64")
    connection.close()

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    sales.to_csv(OUTPUT_FILE, index=False)


if __name__ == "__main__":
    main()
