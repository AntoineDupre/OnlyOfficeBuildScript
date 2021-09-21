FROM ubuntu:14.04

RUN mkdir /onlyoffice
WORKDIR /onlyoffice

VOLUME /onlyoffice
RUN apt-get update
RUN apt-get install -y python git

WORKDIR /onlyoffice/build_tools/tools/linux
CMD ["./automate.py"]
