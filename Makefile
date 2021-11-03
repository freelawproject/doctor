# Run with make push --file docker/django/Makefile
DOCKER_REPOSITORY ?= freelawproject/binary-transformers-and-extractors

DOCKER ?= docker
export DOCKER

DOCKER_TAG = $(shell head -1 version.txt)

.PHONY: all image push

all: image

image:
	$(DOCKER) buildx build --platform linux/amd64,linux/arm64 -t $(DOCKER_REPOSITORY):latest -t $(DOCKER_REPOSITORY):$(DOCKER_TAG) .
	$(DOCKER) buildx build --cache-from=type=local,src=cache -t $(DOCKER_REPOSITORY):latest -t $(DOCKER_REPOSITORY):$(DOCKER_TAG) --load .

push: image
	$(DOCKER) buildx build --push --platform linux/amd64,linux/arm64 -t $(DOCKER_REPOSITORY):latest -t $(DOCKER_REPOSITORY):$(DOCKER_TAG) --file .
