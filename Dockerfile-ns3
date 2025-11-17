FROM ubuntu:24.04

COPY ./openoptics /openoptics
COPY ./openoptics-ns3 /openoptics-ns3

WORKDIR /

RUN apt-get update -qq && \
    apt-get install -y --no-install-recommends \
      python3 python3-pip python3-venv python3-dev \
      build-essential gcc g++ clang \
      cmake make ninja-build pkg-config git\
    && rm -rf /var/lib/apt/lists/*

RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
ENV CC=/usr/bin/gcc CXX=/usr/bin/g++

RUN pip install --upgrade pip setuptools wheel packaging && \
    pip install --no-cache-dir networkx cppyy numpy matplotlib

# WORKDIR /
# RUN git clone --branch optical-switch git@gitlab.mpi-klsb.mpg.de:ylei/openoptics-ns3.git
# COPY ./openoptics-ns3 /openoptics-ns3

WORKDIR /openoptics-ns3
RUN ./ns3 clean
RUN ./ns3 configure --enable-examples --enable-tests --enable-python-bindings
RUN ./ns3 build

# Add built python bindings to the PATH
ENV PATH="/openoptics-ns3/build/lib:${PATH}"
ENV PYTHONPATH="/openoptics-ns3/build/bindings/python"
ENV LD_LIBRARY_PATH="/openoptics-ns3/build/lib"

WORKDIR /openoptics
# Default: open an interactive shell with venv active
CMD ["/bin/bash"]
