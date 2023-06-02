"""Модуль с функцией main"""
import argparse
from caching_dns import CachingDNS


def main():
    """Функция main программы

    """
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="store_true", help="запуск кэширующего DNS сервера")

    args = parser.parse_args()
    if args.start:
        CachingDNS()


if __name__ == "__main__":
    main()
