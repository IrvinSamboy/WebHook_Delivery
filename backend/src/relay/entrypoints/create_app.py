"""Crea una aplicación con su API key: make create-app name="Mi tienda"."""

import argparse

from relay import container


def main() -> None:
    parser = argparse.ArgumentParser(description="Crea una aplicación con su API key.")
    parser.add_argument("name", help="Nombre de la aplicación")
    args = parser.parse_args()

    name = args.name.strip()
    if not name or len(name) > 200:
        parser.error("el nombre debe tener entre 1 y 200 caracteres")

    application, api_key = container.create_application().execute(name)

    print(f"Aplicación: {application.name} ({application.id})")
    print(f"API key:    {api_key}")
    print("Guarda la key ahora: no se puede volver a consultar.")


if __name__ == "__main__":
    main()
