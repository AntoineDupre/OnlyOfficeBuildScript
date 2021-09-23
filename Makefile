
setup_repo:
	echo "Download repo"
	git clone --recursive https://github.com/ONLYOFFICE/DocumentServer.git
	git clone https://github.com/ONLYOFFICE/build_tools.git DocumentServer/build_tools
build:
	docker build -t onlyoffice_builder -f Dockerfile .

compile:
	mkdir -p output
	docker run -it -v $(PWD)/DocumentServer:/onlyoffice -v $(PWD)/output:/var/www/ onlyoffice_builder
