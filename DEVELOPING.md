## Notes

As this is a microservice of Courtlistener, tests are designed to be run from a Mock Courtlistener instance
to verify that the service works as expected and also works across a docker network.  

## Quick start
Generally you can run the following command to build and start your containers
but if you are on a new AMD64 mac, you may need to comment out the build
command and use the makefile to build your images.

    docker-compose -f docker-compose.dev.yml up --build -d

## Testing

Testing is setup with the following default that our tests are run from
a container on the same network as the Doctor machine.  This is modeled after
how we plan to use the Doctor image for CL.

    docker-compose -f docker-compose.dev.yml up --build -d

Starts the Doctor Container and the Mock CL Container that we run our tests from.

    docker exec -it mock_cl_doctor python3 -m unittest doctor.tests

or

    docker exec -it mock_cl_doctor python manage.py test

This is a duplicate of the Doctor container, which we use for simplicity, but it
makes the requests across the docker network.

## Building Images

1. Bump the version number in version.txt.

2. Run `make image --file docker/Makefile` to build or run `make push--file docker/Makefile` to push.
