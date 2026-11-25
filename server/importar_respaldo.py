#!/usr/bin/env python3
"""Importar respaldo JSON v1 de Nosotros, sin imprimir contenido personal."""
import argparse
import json
from pathlib import Path
from app import APIError, storage_arguments, store_from_args


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archivo', type=Path)
    storage_arguments(parser)
    args = parser.parse_args()
    try:
        if args.archivo.stat().st_size > 256 * 1024 * 1024:
            raise APIError('Respaldo demasiado grande')
        with args.archivo.open(encoding='utf-8-sig') as stream:
            document = json.load(stream)
        result = store_from_args(args).import_backup(document)
        print('Respaldo ya importado.' if result['duplicate'] else 'Importación completada: ' + str(result['imported']) + ' registros.')
    except (APIError, OSError, ValueError, RecursionError):
        parser.exit(1, 'Respaldo inválido o almacenamiento no disponible. No se aplicó la importación.\n')


if __name__ == '__main__':
    main()
