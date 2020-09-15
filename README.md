Courtlistener Binary Transformers and Extractors
================================================

Courtlistener Binary Transformers and Extractors is an open source repository to 
maintain, the BTEs used in a docker image for use in Courtlistener.com

Further development is intended and all contributors, corrections and 
additions are welcome.

Background
==========

Free Law Project built this to help ....

We use this docker image inside courtlistener.

Deployment to Docker
====================

1.  Update DOCKER_TAG in hooks/post_push

2.  Commit to master


The post_push is required to generate both latest and version numbering 
in our builds.  If no version number is updated, any commit to master will 
overwrite the latest docker image. 

Testing
=======

Build your docker image before testing it with the following command.

```docker build --tag freelawproject/binary-transformers-and-extractors:latest .```

Future
=======

1) Continue to improve ...
2) Future updates



License
=======

This repository is available under the permissive BSD license, making it easy and safe to incorporate in your own libraries.

Pull and feature requests welcome. Online editing in Github is possible (and easy!)
