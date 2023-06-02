"""Модуль с классом кэширующего DNS сервера"""
import pickle
import socket
import datetime
import sys
import threading

from dnslib import DNSRecord, QTYPE, RR


def read_cache(path_file: str):
    """Функция для чтения серилизованного словаря

    :param path_file: путь до файла с серилизованным объектом
    :return: словарь
    """
    with open(path_file, "rb") as pickle_file:
        try:
            dns_cache = pickle_file.read()
            return pickle.loads(dns_cache)
        except EOFError:
            return {}


def get_request_info(data: bytes):
    """Функция для получения информации из пакета-запроса

    :param data: пакет DNS запроса в виде байтов
    :return: qname, qtype
    """
    request = DNSRecord.parse(data)
    return str(request.q.qname), QTYPE[request.q.qtype]


def get_response_info(data: bytes):
    """Функция для получения информации из пакета-ответа

    :param data: пакет DNS ответа в виде байтов
    :return: возвращает ttl и rdata
    """
    response = DNSRecord.parse(data)
    rdata_list = []

    for rr in response.rr:
        rdata = rr.rdata
        rdata_list.append(rdata)
    return response.rr[0].ttl, rdata_list


class CachingDNS:
    """Класс кэширующего днс сервера"""

    def __init__(self):
        """Функция инициализации класса

        """
        self.dns_cache = read_cache("dns_cache.pickle")
        self.PORT = 53
        self.HOST = "127.0.0.1"
        self.running = True
        self.start_dns()

    def save_dns_cache(self):
        """Функция для серилизации словаря и сохранения его в файл

        """
        with open("dns_cache.pickle", "wb") as pickle_file:
            serialized_data = pickle.dumps(self.dns_cache)
            pickle_file.write(serialized_data)

    def make_request(self,
                     sock_send: socket,
                     sock_rec: socket,
                     data_request: bytes,
                     domain_name: str,
                     q_type: str,
                     address_request: str
                     ):
        """Функция для отправки DNS запроса

        :param sock_send: сокет отправки
        :param sock_rec: сокет получения
        :param data_request: запрос в виде байтов
        :param domain_name: имя домена
        :param q_type: тип запроса
        :param address_request: адрес запроса
        """
        sock_send.sendto(data_request, ("8.8.8.8", 53))
        data_response, address_response = sock_send.recvfrom(1024)
        if data_response:
            try:
                ttl, r_data = get_response_info(data_response)
                current_time = datetime.datetime.now()
                time_end = current_time + datetime.timedelta(milliseconds=ttl)

                self.dns_cache.setdefault(domain_name, {})
                self.dns_cache[domain_name].setdefault(q_type, [r_data, time_end, ttl])

                sock_rec.sendto(data_response, address_request)
            except Exception:
                print("Некорретный запрос")

    def prepare_dns_response(self, data_request: bytes, domain_name: str, q_type: str):
        """Функция подготовки пакета DNS ответа из кэша

        :param data_request: DNS запрос в виде байтов
        :param domain_name: имя домена
        :param q_type: тип запроса
        :return: возвращает подготовленный пакет ответа
        """

        request = DNSRecord.parse(data_request)
        question = request.questions[0]

        r_data_list = self.dns_cache[domain_name][q_type][0]

        response = DNSRecord()
        response.header = request.header
        response.add_question(question)

        for r_data in r_data_list:
            answer = RR(
                rname=question.qname,
                rtype=question.qtype,
                rdata=r_data,
                ttl=int(self.dns_cache[domain_name][q_type][2])
            )
            response.add_answer(answer)
        return response.pack()

    def start_dns(self):
        """Функция запуска DNS сервера

        """
        print("запуск кэширующего DNS сервера")
        print("введите exit для завершения")
        search_expired_records_thread = threading.Thread(
            target=self.search_expired_records,
            args=()
        )
        working_dns_thread = threading.Thread(
            target=self.working_dns,
            args=()
        )

        search_expired_records_thread.start()
        working_dns_thread.start()

        while True:
            stop = input()
            if stop == "exit":
                self.running = False
                self.save_dns_cache()
                print("завершение работы")
                sys.exit(0)

    def search_expired_records(self):
        """Функция просмотра кэша и удаления устаревших записей

        """
        while self.running:
            records_to_remove = []
            for domain_name in self.dns_cache:
                for q_type in self.dns_cache[domain_name]:
                    if self.dns_cache[domain_name][q_type][1] <= datetime.datetime.now():
                        records_to_remove.append([domain_name, q_type])
            for remove_records in records_to_remove:
                domain_name = remove_records[0]
                q_type = remove_records[1]
                print(f"удаление просроченной записи {domain_name} тип {q_type}")
                del self.dns_cache[domain_name][q_type]

    def working_dns(self):
        """Функция, реализующая работу DNS сервера

        """
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock_rec:
            try:
                sock_rec.bind((self.HOST, self.PORT))
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock_send:
                    try:
                        while self.running:
                            sock_rec.settimeout(5)
                            data_request = ""
                            try:
                                data_request, address_request = sock_rec.recvfrom(1024)
                            except ConnectionResetError:
                                if not self.running:
                                    break
                            except TimeoutError:
                                if not self.running:
                                    break

                            if data_request:
                                domain_name, q_type = get_request_info(data_request)

                                if domain_name in self.dns_cache and q_type in self.dns_cache[domain_name]:
                                    if self.dns_cache[domain_name][q_type][1] > datetime.datetime.now():
                                        print(f"запись про домен {domain_name} типа {q_type} взята из кэша")
                                        sock_rec.sendto(
                                            self.prepare_dns_response(
                                                data_request,
                                                domain_name,
                                                q_type
                                            ),
                                            address_request
                                        )
                                    else:
                                        self.make_request(sock_send,
                                                          sock_rec,
                                                          data_request,
                                                          domain_name,
                                                          q_type,
                                                          address_request)
                                else:
                                    self.make_request(sock_send,
                                                      sock_rec,
                                                      data_request,
                                                      domain_name,
                                                      q_type,
                                                      address_request)
                    except socket.error as e:
                        print(f"Ошибка сокета: {e}")
            except socket.error as e:
                print(f"Ошибка сокета: {e}")
