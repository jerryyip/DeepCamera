FROM debian:trixie-slim

ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /work

# 1) tools + GStreamer runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates git python3 python3-pip python3-venv \
    gstreamer1.0-tools \
    gstreamer1.0-plugins-base \
    gstreamer1.0-plugins-good \
    gstreamer1.0-plugins-bad \
    gstreamer1.0-plugins-ugly \
    gstreamer1.0-libav \
    libgstreamer1.0-0 \
    libgstreamer-plugins-base1.0-0 \
    wget xz-utils nano \
    && rm -rf /var/lib/apt/lists/*

# 2) HailoRT + GStreamer Hailo plugins + Python bindings
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg python3-virtualenv gcc-12 g++-12 python-gi-dev pkg-config libcairo2-dev \
    libgirepository1.0-dev libgstreamer1.0-dev cmake libgstreamer-plugins-base1.0-dev \
    libzmq3-dev libgstreamer-plugins-bad1.0-dev gstreamer1.0-plugins-bad \
    gstreamer1.0-libav libopencv-dev python3-opencv rapidjson-dev

RUN apt-get install -y --no-install-recommends \
    python3-gi gir1.2-gtk-3.0 libgtk-3-0

RUN wget https://archive.raspberrypi.org/debian/pool/main/h/hailort/hailort_4.23.0_arm64.deb -O /tmp/hailort.deb
RUN set -eux; \
    mkdir -p /tmp/hailort_extract; \
    cd /tmp/hailort_extract; \
    ar x /tmp/hailort.deb; \
    tar -xf data.tar.* -C /tmp/hailort_extract; \
    cp -a /tmp/hailort_extract/usr/* /usr; \
    ldconfig; \
    rm -rf /tmp/hailort_extract /tmp/hailort.deb

RUN wget https://archive.raspberrypi.org/debian/pool/main/h/hailo-tappas-core/hailo-tappas-core_5.1.0_arm64.deb -O /tmp/hailo-tappas-core.deb 
RUN apt-get install -y /tmp/hailo-tappas-core.deb && rm -f /tmp/hailo-tappas-core.deb

RUN wget http://dev-public.hailo.ai/2025_10/Hailo8/hailo_tappas_core_python_binding-5.1.0-py3-none-any.whl -O /tmp/hailo_tappas_core_python_binding-5.1.0-py3-none-any.whl
RUN pip3 install /tmp/hailo_tappas_core_python_binding-5.1.0-py3-none-any.whl  --break-system-packages  && rm -f /tmp/hailo_tappas_core_python_binding-5.1.0-py3-none-any.whl

RUN wget http://dev-public.hailo.ai/2025_10/Hailo8/hailort-4.23.0-cp313-cp313-linux_aarch64.whl -O /tmp/hailort-4.23.0-cp313-cp313-linux_aarch64.whl
RUN pip3 install /tmp/hailort-4.23.0-cp313-cp313-linux_aarch64.whl  --break-system-packages && rm -f /tmp/hailort-4.23.0-cp313-cp313-linux_aarch64.whl

# 3) hailo-apps (GStreamer pipelines / examples / models)
RUN git clone --depth 1 https://github.com/hailo-ai/hailo-apps.git /opt/hailo-apps
WORKDIR /opt/hailo-apps
RUN pip3 install setproctitle dotenv pyyaml --break-system-packages
RUN apt-get install -y --no-install-recommends \
    meson ninja-build
WORKDIR /opt/hailo-apps/hailo_apps/postprocess/
RUN ./compile_postprocess.sh
ADD ./models/detection/*.hef /usr/local/hailo/resources/models/hailo8/

# 4) novnc setup
# Install some basic utilities
RUN apt-get update && apt-get install -y \
    libx11-6 \
    libglib2.0-0 \
    tzdata \
    bash \
    fluxbox \
    net-tools \
    novnc \
    supervisor \
    x11vnc \
    xterm \
    xvfb \
    libsm6 \
    libxext6 \
    qt5dxcb-plugin

ENV LANG=en_US.UTF-8 \
    LANGUAGE=en_US.UTF-8 \
    LC_ALL=C.UTF-8 \
    DISPLAY=:0.0 \
    DISPLAY_WIDTH=1024 \
    DISPLAY_HEIGHT=768 \
    RUN_XTERM=yes \
    RUN_FLUXBOX=yes

# 5) copy application files
RUN pip3 install flask --break-system-packages
ADD ./docker-novnc /app/docker-novnc
ADD ./detector.py /opt/hailo-apps/
ADD ./resources/* /app/resources/

WORKDIR /app

CMD ["/app/docker-novnc/entrypoint.sh"]
EXPOSE 8080