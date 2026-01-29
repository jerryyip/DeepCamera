import os
import sys
import threading
from pathlib import Path
from uuid import uuid4

import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst, GLib

from flask import Flask, jsonify, request
from werkzeug.utils import secure_filename

import hailo
from hailo_apps.python.core.common.core import get_default_parser, get_resource_path
from hailo_apps.python.core.common.defines import (
    RESOURCES_MODELS_DIR_NAME,
    RESOURCES_SO_DIR_NAME,
    RESOURCES_VIDEOS_DIR_NAME,
    SIMPLE_DETECTION_PIPELINE,
    SIMPLE_DETECTION_POSTPROCESS_FUNCTION,
    SIMPLE_DETECTION_POSTPROCESS_SO_FILENAME,
    SIMPLE_DETECTION_VIDEO_NAME,
)
from hailo_apps.python.core.common.hailo_logger import get_logger
from hailo_apps.python.core.gstreamer.gstreamer_app import (
    GStreamerApp,
    app_callback_class,
)
from hailo_apps.python.core.gstreamer.gstreamer_helper_pipelines import (
    DISPLAY_PIPELINE,
    INFERENCE_PIPELINE,
    SOURCE_PIPELINE,
    USER_CALLBACK_PIPELINE,
    get_source_type,
)

hailo_logger = get_logger(__name__)

UPLOAD_DIR = Path("local_resources") / "uploads"
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".gif"}


# User-defined class to be used in the callback function: Inheritance from the app_callback_class
class user_app_callback_class(app_callback_class):
    def __init__(self):
        super().__init__()


# User-defined callback function: This is the callback function that will be called when data is available from the pipeline
def app_callback(element, buffer, user_data):
    # Note: frame counting is handled by the framework wrapper.
    string_to_print = f"Frame count: {user_data.get_count()}\n"
    if buffer is None:  # Check if the buffer is valid
        return
    for detection in hailo.get_roi_from_buffer(buffer).get_objects_typed(hailo.HAILO_DETECTION):  # Get the detections from the buffer & Parse the detections
        string_to_print += (f"Detection: {detection.get_label()} Confidence: {detection.get_confidence():.2f}\n")
    print(string_to_print)
    return


class GStreamerDetectionSimpleApp(GStreamerApp):
    def __init__(self, app_callback, user_data, parser=None):
        if parser is None:
            parser = get_default_parser()
        parser.add_argument(
            "--labels-json",
            default=None,
            help="Path to costume labels JSON file",
        )
        hailo_logger.info("Initializing GStreamer Detection Simple App...")
        super().__init__(parser, user_data)

        if self.video_width == 1280:
            self.video_width = 640
        if self.video_height == 720:
            self.video_height = 640

        if self.batch_size == 1:
            self.batch_size = 2

        nms_score_threshold = 0.3
        nms_iou_threshold = 0.45
        if self.options_menu.input is None:
            self.video_source = get_resource_path(
                pipeline_name=SIMPLE_DETECTION_PIPELINE,
                resource_type=RESOURCES_VIDEOS_DIR_NAME,
                arch=self.arch,
                model=SIMPLE_DETECTION_VIDEO_NAME,
            )

        if self.options_menu.hef_path is not None:
            self.hef_path = self.options_menu.hef_path
        else:
            self.hef_path = get_resource_path(
                pipeline_name=SIMPLE_DETECTION_PIPELINE,
                resource_type=RESOURCES_MODELS_DIR_NAME,
                arch=self.arch,
            )
        hailo_logger.info(f"Using HEF path: {self.hef_path}")

        self.post_process_so = get_resource_path(
            pipeline_name=SIMPLE_DETECTION_PIPELINE,
            resource_type=RESOURCES_SO_DIR_NAME,
            arch=self.arch,
            model=SIMPLE_DETECTION_POSTPROCESS_SO_FILENAME,
        )
        hailo_logger.info(f"Using post-process shared object: {self.post_process_so}")

        self.post_function_name = SIMPLE_DETECTION_POSTPROCESS_FUNCTION
        self.labels_json = self.options_menu.labels_json
        self.app_callback = app_callback
        self.thresholds_str = (
            f"nms-score-threshold={nms_score_threshold} "
            f"nms-iou-threshold={nms_iou_threshold} "
            f"output-format-type=HAILO_FORMAT_TYPE_FLOAT32"
        )
        self.is_image_input = self._is_image_input(self.video_source)

        hailo_logger.info(f"Using thresholds: {self.thresholds_str}")

        self.create_pipeline()

    @staticmethod
    def _is_image_input(video_source):
        if not video_source:
            return False
        if str(video_source).startswith("rtsp://"):
            return False
        source_path = Path(str(video_source))
        return source_path.is_file() and source_path.suffix.lower() in IMAGE_EXTS

    def get_pipeline_string(self):
        if self.is_image_input:
            source_pipeline = (
                f'multifilesrc location="{self.video_source}" loop=false num-buffers=1 ! '
                f'decodebin ! imagefreeze ! videoconvert n-threads=4 qos=false ! '
                f'videoscale n-threads=2 ! '
                f'video/x-raw, format=RGB, pixel-aspect-ratio=1/1, width={self.video_width}, height={self.video_height} '
            )
        else:
            source_pipeline = SOURCE_PIPELINE(
                video_source=self.video_source,
                video_width=self.video_width,
                video_height=self.video_height,
                frame_rate=self.frame_rate,
                sync=self.sync,
                no_webcam_compression=True,
            )

        detection_pipeline = INFERENCE_PIPELINE(
            hef_path=self.hef_path,
            post_process_so=self.post_process_so,
            post_function_name=self.post_function_name,
            batch_size=self.batch_size,
            config_json=self.labels_json,
            additional_params=self.thresholds_str,
        )
        user_callback_pipeline = USER_CALLBACK_PIPELINE()
        display_pipeline = DISPLAY_PIPELINE(
            video_sink=self.video_sink, sync=self.sync, show_fps=self.show_fps
        )

        pipeline_string = (
            f"{source_pipeline} ! "
            f"{detection_pipeline} ! "
            f"{user_callback_pipeline} ! "
            f"{display_pipeline}"
        )
        hailo_logger.info(f"Pipeline string: {pipeline_string}")
        return pipeline_string


class GstService:
    def __init__(self, gst_app: GStreamerDetectionSimpleApp):
        self.gst_app = gst_app
        self.lock = threading.Lock()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.gst_app.run, daemon=True)
        self.thread.start()
        return self.thread

    def switch_source(self, new_source: str):
        with self.lock:
            self.gst_app.video_source = new_source
            self.gst_app.options_menu.input = new_source
            self.gst_app.source_type = get_source_type(new_source)
            self.gst_app.sync = (
                "true" if (self.gst_app.source_type == "file" and not self.gst_app.options_menu.disable_sync) else "false"
            )
            self.gst_app.is_image_input = self.gst_app._is_image_input(new_source)
            GLib.idle_add(self.gst_app._rebuild_pipeline)


flask_app = Flask(__name__)
gst_service = None


def _ensure_upload_dir():
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _save_uploaded_file(file_storage):
    _ensure_upload_dir()
    original_name = secure_filename(file_storage.filename)
    suffix = Path(original_name).suffix
    dest_path = UPLOAD_DIR / f"{uuid4().hex}{suffix}"
    file_storage.save(dest_path)
    return str(dest_path)


def _extract_path_from_request(expected_kind: str):
    if "file" in request.files:
        file_storage = request.files["file"]
        if not file_storage.filename:
            return None, "empty filename"
        path = _save_uploaded_file(file_storage)
        if expected_kind == "image":
            if Path(path).suffix.lower() not in IMAGE_EXTS:
                return None, "file is not a supported image"
        return path, None

    data = request.get_json(silent=True) or {}
    path = data.get("path") or data.get("video_path") or data.get("image_path")
    if not path:
        return None, "missing path"
    return path, None


def _validate_existing_path(path: str):
    path_obj = Path(path)
    if not path_obj.exists():
        return False, f"path does not exist: {path}"
    return True, None


@flask_app.route("/submit/video_path", methods=["POST"])
def submit_video_path():
    if gst_service is None:
        return jsonify({"ok": False, "error": "gst service not initialized"}), 500

    path, err = _extract_path_from_request("video")
    if err:
        return jsonify({"ok": False, "error": err}), 400

    if path.startswith("rtsp://"):
        return jsonify({"ok": False, "error": "rtsp url must use /submit/rtsp"}), 400

    ok, err = _validate_existing_path(path)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    gst_service.switch_source(path)
    return jsonify({"ok": True, "source": path})


@flask_app.route("/submit/image", methods=["POST"])
def submit_image():
    if gst_service is None:
        return jsonify({"ok": False, "error": "gst service not initialized"}), 500

    path, err = _extract_path_from_request("image")
    if err:
        return jsonify({"ok": False, "error": err}), 400

    if path.startswith("rtsp://"):
        return jsonify({"ok": False, "error": "rtsp url must use /submit/rtsp"}), 400

    ok, err = _validate_existing_path(path)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    if Path(path).suffix.lower() not in IMAGE_EXTS:
        return jsonify({"ok": False, "error": "unsupported image extension"}), 400

    gst_service.switch_source(path)
    return jsonify({"ok": True, "source": path})


@flask_app.route("/submit/rtsp", methods=["POST"])
def submit_rtsp():
    if gst_service is None:
        return jsonify({"ok": False, "error": "gst service not initialized"}), 500

    data = request.get_json(silent=True) or {}
    url = data.get("url") or data.get("rtsp")
    if not url:
        return jsonify({"ok": False, "error": "missing rtsp url"}), 400
    if not url.startswith("rtsp://"):
        return jsonify({"ok": False, "error": "invalid rtsp url"}), 400

    gst_service.switch_source(url)
    return jsonify({"ok": True, "source": url})


def _build_gst_app(initial_input: str | None, frame_rate: str | None, hef_path: str | None):
    argv = [sys.argv[0]]
    if initial_input:
        argv += ["--input", initial_input]
    
    if frame_rate:
        argv += ["--frame-rate", frame_rate]
        argv += ["--show-fps"]
    
    if hef_path:
        argv += ["--hef-path", hef_path]

    original_argv = sys.argv
    sys.argv = argv
    try:
        user_data = user_app_callback_class()
        gst_app = GStreamerDetectionSimpleApp(app_callback, user_data)
    finally:
        sys.argv = original_argv

    return gst_app


def _init_env():
    project_root = Path(__file__).resolve().parent.parent
    env_file = project_root / ".env"
    os.environ["HAILO_ENV_FILE"] = str(env_file)
    os.environ["HAILO_MONITOR"] = "1"


if __name__ == "__main__":
    _init_env()

    # default_rtsp = os.environ.get(
    #     "RTSP_URL",
    #     "rtsp://127.0.0.1:554/",
    # )

    default_video = os.environ.get(
        "VIDEO_PATH",
        "/app/resources/test_720p_h264_30s.mp4",
    )

    default_fps = os.environ.get(
        "FPS",
        "15",
    )

    default_hef = os.environ.get(
        "HEF_PATH",
        "/usr/local/hailo/resources/models/hailo8/yolov7.hef",
    )

    gst_app = _build_gst_app(default_video, default_fps, default_hef)
    gst_service = GstService(gst_app)
    gst_service.start()

    host = os.environ.get("FLASK_HOST", "0.0.0.0")
    port = int(os.environ.get("FLASK_PORT", "3000"))
    flask_app.run(host=host, port=port)
