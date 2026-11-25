#!/usr/bin/env python3
"""Respaldo consistente SQLite + imágenes. Contiene credenciales/sesiones: guardar privado."""
import argparse
from app import storage_arguments, store_from_args, APIError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    storage_arguments(parser)
    parser.add_argument('--daily', action='store_true', help='No repetir el respaldo del día UTC')
    args = parser.parse_args()
    try:
        store_from_args(args).backup(daily=args.daily)
        print('Respaldo creado o ya existente. Incluye autenticación; mantener privado.')
    except (APIError, OSError) as error:
        parser.exit(1, 'No se pudo crear el respaldo.\n')


if __name__ == '__main__':
    main()
