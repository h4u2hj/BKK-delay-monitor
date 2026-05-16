from bkk_delays.app import create_app


def main() -> None:
    app = create_app()
    app.run(debug=True)


if __name__ == "__main__":
    main()
