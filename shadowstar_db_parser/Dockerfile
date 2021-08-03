FROM ubuntu:20.04

RUN apt-get -yqq update

RUN apt-get -yqq install wget unzip python3-pip python3-dev

RUN mkdir -p /opt/shadowstar-db-parser/databases/

COPY parser.py /opt/shadowstar-db-parser/
COPY requirements.txt /opt/shadowstar-db-parser/
COPY download_dumps.sh /opt/shadowstar-db-parser/

WORKDIR /opt/shadowstar-db-parser/

RUN pip3 install --upgrade -r requirements.txt

CMD [ "python3", "parser.py", "-d", "-o", "network_info.tsv" ]
