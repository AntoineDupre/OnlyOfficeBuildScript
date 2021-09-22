### Build onlyoffice from sources

Makefile to build onlyoffice from sources, it uses a docker image (ubuntu:14.04) and [official build tools](https://github.com/ONLYOFFICE/build_tools)

```
# Setup environement repos
make setup_repo
# Prepare docker image
make build
# Compile sources
make compile
```
