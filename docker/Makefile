# Run with make push --file docker/Makefile -e VERSION=$(git rev-parse --short HEAD)
# Note that makefiles differentiate between tabs and spaces in a weird way!

# Ensure VERSION is set.
ifndef VERSION
$(error VERSION variable is not set. Use -e VERSION=XYZ to proceed.)
endif

DOCKER_REPOSITORY ?= freelawproject/doctor

DOCKER ?= docker
export DOCKER

.PHONY: all image push multiarch_push multiarch_image

UNAME := $(shell uname -m)

all: image

image:
	$(DOCKER) build -t $(DOCKER_REPOSITORY):$(VERSION) -t $(DOCKER_REPOSITORY):latest --file docker/Dockerfile .

push: image
	$(info Checking if valid architecture)
	@if [ $(UNAME) = "x86_64" ]; then \
		echo "Architecture is OK. Pushing.";\
		$(DOCKER) push $(DOCKER_REPOSITORY):$(VERSION);\
        $(DOCKER) push $(DOCKER_REPOSITORY):latest;\
	else \
		echo "Only arm64 machines can push single-architecture builds. If you want to \
push a build, try 'make multiarch_push', which builds for both arm64 and amd64. This \
protects against arm64 builds being accidentally deployed to the server (which uses arm64).";\
	fi

multiarch_image:
	export DOCKER_CLI_EXPERIMENTAL=enabled
	$(DOCKER) buildx rm
	$(DOCKER) buildx create --use --name flp-builder
	$(DOCKER) buildx build --platform linux/amd64,linux/arm64 -t $(DOCKER_REPOSITORY):latest -t $(DOCKER_REPOSITORY):$(VERSION) --file docker/Dockerfile .

multiarch_push: multiarch_image
	$(DOCKER) buildx build --push --platform linux/amd64,linux/arm64 -t $(DOCKER_REPOSITORY):latest -t $(DOCKER_REPOSITORY):$(VERSION) --file docker/Dockerfile .

x86_push:
	export DOCKER_CLI_EXPERIMENTAL=enabled
	$(DOCKER) buildx rm
	$(DOCKER) buildx create --use --name flp-builder
	$(DOCKER) buildx build --push --platform linux/amd64 -t $(DOCKER_REPOSITORY):latest -t $(DOCKER_REPOSITORY):$(VERSION) --file docker/Dockerfile .
