"""Local reference server; debug/reloader disabled."""
import argparse
from .app import create_app


def main():
    parser = argparse.ArgumentParser(description='B04 C1 T03-T05 reference backend')
    parser.add_argument('--database', required=True, help='B04-local reference database file')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    app = create_app(database_path=args.database)
    try:
        app.run(host='127.0.0.1', port=args.port, debug=False, use_reloader=False)
    finally:
        app.extensions['b04_reference_backend'].repository.close()


if __name__ == '__main__':
    main()
