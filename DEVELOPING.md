## Notes

As this is a microservice of Courtlistner, tests are designed to be run from a Mock Courtlistener instance
to verify that the service works as expected and also works across a docker network.  

## Quick start

    docker-compose -f docker-compose.dev.yml up --build -d


## Testing 

Testing is setup with the following default that our tests are run from
a container on the same network as the BTE machine.  This is modeled after
how we plan to use the BTE image for CL.

    docker-compose -f docker-compose.dev.yml up --build -d

Starts the BTE Container and the Mock CL Container that we run our tests from.

    docker exec -it mock_courtlistener python3 -m unittest bte.tests

This is a duplicate of the BTE container, which we use for simplicity, but it
makes the requests across the docker network.

## Building Images

A soon to be written make file will certainly be used to build and push images to docker hub.
