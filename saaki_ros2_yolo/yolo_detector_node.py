#!/usr/bin/env python3
# ROS 2 node that requests frames from videohub and runs YOLO detection.
import json
import time
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from sensor_msgs.msg import Image
from std_msgs.msg import Header, String
from unitree_api.msg import Request, Response

# Optional imports are handled explicitly so startup errors can point the user
# to the missing dependency instead of failing later during runtime.
try:
    from vision_msgs.msg import Detection2D, Detection2DArray, ObjectHypothesisWithPose
except ImportError:
    Detection2D = None
    Detection2DArray = None
    ObjectHypothesisWithPose = None

try:
    import torch
except ImportError:
    torch = None

try:
    from ultralytics import YOLO
except ImportError:
    YOLO = None


def _resolve_label(names: Any, class_id: int) -> str:
    # Return the human-readable class label reported by the YOLO model.
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, list) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _bgr_to_image_msg(image: np.ndarray, header: Header) -> Image:
    # Convert an OpenCV BGR image into a ROS Image message.
    msg = Image()
    msg.header = header
    msg.height = int(image.shape[0])
    msg.width = int(image.shape[1])
    msg.encoding = "bgr8"
    msg.is_bigendian = False
    msg.step = int(image.shape[1] * 3)
    msg.data = image.tobytes()
    return msg


def _color_for_class(class_id: int) -> Tuple[int, int, int]:
    # Generate a stable BGR color so each class is drawn consistently.
    base = int(class_id) * 57
    return (
        (37 + base * 17) % 255,
        (89 + base * 29) % 255,
        (173 + base * 43) % 255,
    )


class SaakiRos2YoloNode(Node):
    # Fetch frames from Unitree videohub, run YOLO, and publish detections.
    def __init__(self) -> None:
        super().__init__("saaki_ros2_yolo_node")

        # Parameters for the request/response flow used to obtain camera frames.
        self.declare_parameter("request_topic", "/api/videohub/request")
        self.declare_parameter("response_topic", "/api/videohub/response")
        self.declare_parameter("video_api_id", 1001)
        self.declare_parameter("request_timeout_sec", 0.5)
        self.declare_parameter("target_fps", 15.0)
        self.declare_parameter("frame_id", "g1_front_camera")

        # Parameters controlling the standard ROS outputs of this node.
        self.declare_parameter("detections_topic", "/g1/yolo/detections_2d")
        self.declare_parameter("annotated_image_topic", "/g1/yolo/annotated_image")
        self.declare_parameter("publish_annotated_image", True)
        self.declare_parameter("annotated_image_max_fps", 15.0)
        self.declare_parameter("annotated_image_scale", 0.33)

        # Optional legacy JSON output kept for consumers not using vision_msgs.
        self.declare_parameter("publish_legacy_json", True)
        self.declare_parameter("legacy_detections_topic", "/g1/yolo/detections")

        # YOLO model and inference settings.
        self.declare_parameter("model_path", "yolov8n.pt")
        self.declare_parameter("device", "auto")
        self.declare_parameter("conf_threshold", 0.25)
        self.declare_parameter("iou_threshold", 0.45)
        self.declare_parameter("max_detections", 50)

        self.request_topic = str(self.get_parameter("request_topic").value)
        self.response_topic = str(self.get_parameter("response_topic").value)
        self.video_api_id = int(self.get_parameter("video_api_id").value)
        self.request_timeout_sec = max(
            0.05, float(self.get_parameter("request_timeout_sec").value)
        )
        self.target_fps = float(self.get_parameter("target_fps").value)
        self.frame_id = str(self.get_parameter("frame_id").value)

        self.detections_topic = str(self.get_parameter("detections_topic").value)
        self.annotated_image_topic = str(
            self.get_parameter("annotated_image_topic").value
        )
        self.publish_annotated_image = bool(
            self.get_parameter("publish_annotated_image").value
        )
        self.annotated_image_max_fps = float(
            self.get_parameter("annotated_image_max_fps").value
        )
        self.annotated_image_scale = float(
            self.get_parameter("annotated_image_scale").value
        )

        self.publish_legacy_json = bool(self.get_parameter("publish_legacy_json").value)
        self.legacy_detections_topic = str(
            self.get_parameter("legacy_detections_topic").value
        )

        self.model_path = str(self.get_parameter("model_path").value)
        self.device_param = str(self.get_parameter("device").value)
        self.conf_threshold = float(self.get_parameter("conf_threshold").value)
        self.iou_threshold = float(self.get_parameter("iou_threshold").value)
        self.max_detections = max(1, int(self.get_parameter("max_detections").value))

        # Clamp misconfigured parameters to safe values so the node can still run.
        if self.target_fps <= 0.0:
            self.get_logger().warn("target_fps must be > 0.0. Falling back to 15.0 FPS")
            self.target_fps = 15.0

        if self.annotated_image_max_fps < 0.0:
            self.get_logger().warn(
                "annotated_image_max_fps cannot be negative. Falling back to 0.0 (no limit)"
            )
            self.annotated_image_max_fps = 0.0

        if self.annotated_image_scale <= 0.0:
            self.get_logger().warn(
                "annotated_image_scale must be > 0.0. Falling back to 1.0"
            )
            self.annotated_image_scale = 1.0

        # Fail fast if required runtime dependencies are missing.
        if Detection2DArray is None or Detection2D is None or ObjectHypothesisWithPose is None:
            raise RuntimeError(
                "vision_msgs is not installed. Install with: sudo apt install ros-humble-vision-msgs"
            )

        if YOLO is None:
            raise RuntimeError(
                "ultralytics is not installed. Install with: pip install ultralytics"
            )

        self.device = self._resolve_device(self.device_param)
        self.model = YOLO(self.model_path)

        # ROS interfaces: one publisher/subscriber pair for videohub traffic and
        # one or more publishers for the processed outputs.
        self.request_pub = self.create_publisher(Request, self.request_topic, 1)
        self.response_sub = self.create_subscription(
            Response, self.response_topic, self._response_callback, 10
        )

        self.detections_pub = self.create_publisher(
            Detection2DArray, self.detections_topic, 10
        )

        self.annotated_pub: Optional[Any] = None
        self.annotated_publish_period_sec = (
            1.0 / self.annotated_image_max_fps
            if self.annotated_image_max_fps > 0.0
            else 0.0
        )
        self.last_annotated_publish_monotonic = 0.0
        if self.publish_annotated_image:
            self.annotated_pub = self.create_publisher(
                Image, self.annotated_image_topic, 10
            )

        self.legacy_pub: Optional[Any] = None
        if self.publish_legacy_json:
            self.legacy_pub = self.create_publisher(
                String, self.legacy_detections_topic, 10
            )

        # Only one videohub request is kept in flight at a time so responses can
        # be matched reliably and old frames can be discarded on timeout.
        self.pending_request_id: Optional[int] = None
        self.pending_request_sent_monotonic = 0.0

        self._log_times: Dict[str, float] = {}

        # The timer drives frame acquisition; actual inference happens when the
        # corresponding videohub response arrives.
        self.timer = self.create_timer(1.0 / self.target_fps, self._timer_callback)

        self.get_logger().info(
            "Started saaki_ros2_yolo_node "
            f"(request_topic={self.request_topic}, response_topic={self.response_topic}, "
            f"api_id={self.video_api_id}, model_path={self.model_path}, device={self.device}, "
            f"target_fps={self.target_fps}, detections_topic={self.detections_topic}, "
            f"annotated_scale={self.annotated_image_scale}, "
            f"annotated_max_fps={self.annotated_image_max_fps})"
        )

    def _resolve_device(self, device_param: str) -> str:
        # Choose the inference device, preferring CUDA when `auto` is used.
        if device_param.lower() != "auto":
            return device_param

        if torch is not None:
            try:
                if torch.cuda.is_available():
                    return "cuda:0"
            except Exception:
                pass

        return "cpu"

    def _timer_callback(self) -> None:
        # Request a new frame when there is no pending videohub request.
        now = time.monotonic()

        if self.pending_request_id is not None:
            if now - self.pending_request_sent_monotonic > self.request_timeout_sec:
                self._throttled_log(
                    "request_timeout",
                    "warn",
                    f"Videohub request timed out after {self.request_timeout_sec:.2f}s; dropping pending request",
                    period_sec=2.0,
                )
                self.pending_request_id = None
                self.pending_request_sent_monotonic = 0.0
            return

        # Use the request id to pair the next response with this timer tick.
        request_id = int(time.time_ns() % ((1 << 63) - 1))
        req = Request()
        req.header.identity.id = request_id
        req.header.identity.api_id = self.video_api_id
        req.header.policy.priority = 0
        req.header.policy.noreply = False
        req.parameter = "{}"

        self.request_pub.publish(req)
        self.pending_request_id = request_id
        self.pending_request_sent_monotonic = now

    def _response_callback(self, msg: Response) -> None:
        # Decode the returned frame, run YOLO, and publish the outputs.
        # Ignore unrelated videohub traffic and stale replies.
        if msg.header.identity.api_id != self.video_api_id:
            return

        if self.pending_request_id is None:
            return

        if msg.header.identity.id != self.pending_request_id:
            return

        self.pending_request_id = None
        self.pending_request_sent_monotonic = 0.0

        if msg.header.status.code != 0:
            self._throttled_log(
                "bad_status",
                "warn",
                f"videohub response error status: {msg.header.status.code}",
            )
            return

        if len(msg.binary) == 0:
            self._throttled_log(
                "empty_binary",
                "warn",
                "videohub response contains empty binary payload",
            )
            return

        # The videohub payload contains JPEG bytes that must be decoded before
        # they can be passed to YOLO or published as annotated images.
        jpeg_bytes = bytes(msg.binary)
        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            self._throttled_log(
                "decode_failed",
                "warn",
                "OpenCV failed to decode JPEG frame from videohub payload",
            )
            return

        # Reuse a single ROS timestamp/header across every output generated from
        # this frame so detections and images stay aligned.
        stamp = self.get_clock().now().to_msg()
        header = Header()
        header.stamp = stamp
        header.frame_id = self.frame_id

        infer_t0 = time.perf_counter()
        try:
            results = self.model.predict(
                source=frame,
                conf=self.conf_threshold,
                iou=self.iou_threshold,
                device=self.device,
                max_det=self.max_detections,
                verbose=False,
            )
        except Exception as exc:
            self._throttled_log("inference_failed", "error", f"YOLO inference failed: {exc}")
            return

        inference_ms = (time.perf_counter() - infer_t0) * 1000.0
        result = results[0] if results else None

        # Publish the structured detection message first, then the optional
        # compatibility outputs derived from the same inference result.
        detection_msg, legacy_dets = self._build_detections(result, header)
        self.detections_pub.publish(detection_msg)

        if self.legacy_pub is not None:
            payload: Dict[str, Any] = {
                "stamp": {
                    "sec": int(header.stamp.sec),
                    "nanosec": int(header.stamp.nanosec),
                },
                "frame_id": header.frame_id,
                "image_size": {
                    "width": int(frame.shape[1]),
                    "height": int(frame.shape[0]),
                },
                "inference_ms": round(inference_ms, 2),
                "detections": legacy_dets,
            }

            legacy_msg = String()
            legacy_msg.data = json.dumps(payload, separators=(",", ":"))
            self.legacy_pub.publish(legacy_msg)

        if self.annotated_pub is not None and result is not None:
            now_monotonic = time.monotonic()
            # Annotated image publishing can be rate-limited separately from
            # frame acquisition so visualization does not dominate bandwidth.
            if (
                self.annotated_publish_period_sec > 0.0
                and now_monotonic - self.last_annotated_publish_monotonic
                < self.annotated_publish_period_sec
            ):
                return
            try:
                annotated = self._build_annotated_image(frame, result)
                self.annotated_pub.publish(_bgr_to_image_msg(annotated, header))
                self.last_annotated_publish_monotonic = now_monotonic
            except Exception as exc:
                self._throttled_log(
                    "annotate_failed",
                    "warn",
                    f"Failed to publish annotated image: {exc}",
                )

    def _resize_annotated_image(self, image: np.ndarray, scale: float) -> np.ndarray:
        # Resize the visualization image while keeping at least one pixel.
        width = max(1, int(image.shape[1] * scale))
        height = max(1, int(image.shape[0] * scale))
        interpolation = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        return cv2.resize(image, (width, height), interpolation=interpolation)

    def _build_annotated_image(self, frame: np.ndarray, result: Optional[Any]) -> np.ndarray:
        # Draw YOLO boxes and labels onto a copy of the frame for visualization.
        if self.annotated_image_scale != 1.0:
            annotated = self._resize_annotated_image(frame, self.annotated_image_scale)
        else:
            annotated = frame.copy()

        if result is None or result.boxes is None:
            return annotated

        names = result.names
        scale_x = annotated.shape[1] / float(frame.shape[1])
        scale_y = annotated.shape[0] / float(frame.shape[0])

        # Boxes are predicted in the original image coordinates, so rescale them
        # before drawing when a smaller annotated image is requested.
        for box in result.boxes:
            xyxy = box.xyxy[0].tolist()
            x_min = int(float(xyxy[0]) * scale_x)
            y_min = int(float(xyxy[1]) * scale_y)
            x_max = int(float(xyxy[2]) * scale_x)
            y_max = int(float(xyxy[3]) * scale_y)

            x_min = max(0, min(annotated.shape[1] - 1, x_min))
            y_min = max(0, min(annotated.shape[0] - 1, y_min))
            x_max = max(0, min(annotated.shape[1] - 1, x_max))
            y_max = max(0, min(annotated.shape[0] - 1, y_max))

            class_id = int(box.cls[0]) if box.cls is not None else -1
            score = float(box.conf[0]) if box.conf is not None else 0.0
            label = _resolve_label(names, class_id)
            color = _color_for_class(class_id)

            cv2.rectangle(annotated, (x_min, y_min), (x_max, y_max), color, 2)
            caption = f"{label} {score:.2f}"
            text_y = y_min - 8 if y_min > 16 else y_min + 16
            cv2.putText(
                annotated,
                caption,
                (x_min, text_y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                color,
                2,
                cv2.LINE_AA,
            )

        return annotated

    def _build_detections(
        self, result: Optional[Any], header: Header
    ) -> Tuple[Detection2DArray, List[Dict[str, Any]]]:
        # Convert YOLO results into vision_msgs and legacy JSON-friendly data.
        msg = Detection2DArray()
        msg.header = header
        legacy_detections: List[Dict[str, Any]] = []

        if result is None or result.boxes is None:
            return msg, legacy_detections

        names = result.names
        stamp_ns = int(header.stamp.sec) * 1_000_000_000 + int(header.stamp.nanosec)

        for idx, box in enumerate(result.boxes):
            xyxy = box.xyxy[0].tolist()
            x_min, y_min, x_max, y_max = [float(v) for v in xyxy]

            if x_max < x_min:
                x_min, x_max = x_max, x_min
            if y_max < y_min:
                y_min, y_max = y_max, y_min

            # vision_msgs stores bounding boxes as center point plus width/height.
            width = max(0.0, x_max - x_min)
            height = max(0.0, y_max - y_min)
            center_x = x_min + 0.5 * width
            center_y = y_min + 0.5 * height

            class_id = int(box.cls[0]) if box.cls is not None else -1
            score = float(box.conf[0]) if box.conf is not None else 0.0
            label = _resolve_label(names, class_id)

            det = Detection2D()
            det.header = header
            # Some consumers expect a stable detection id; use timestamp + index
            # when the message definition supports that field.
            if hasattr(det, "id"):
                det.id = f"{stamp_ns}_{idx}"

            self._set_bbox_center(det, center_x, center_y)
            if hasattr(det.bbox, "size_x"):
                det.bbox.size_x = width
            if hasattr(det.bbox, "size_y"):
                det.bbox.size_y = height

            hyp = ObjectHypothesisWithPose()
            hyp.hypothesis.class_id = label
            hyp.hypothesis.score = score
            det.results.append(hyp)
            msg.detections.append(det)

            legacy_detections.append(
                {
                    "class_id": class_id,
                    "label": label,
                    "score": round(score, 4),
                    "bbox_xyxy": {
                        "x_min": round(x_min, 2),
                        "y_min": round(y_min, 2),
                        "x_max": round(x_max, 2),
                        "y_max": round(y_max, 2),
                    },
                }
            )

        return msg, legacy_detections

    def _set_bbox_center(self, det: Detection2D, center_x: float, center_y: float) -> None:
        # Fill the Detection2D center fields across vision_msgs variants.
        center = det.bbox.center

        # Different ROS distributions expose the center either as Pose2D-like
        # fields or as a full 3D pose. Support both layouts without branching
        # elsewhere in the code.
        if hasattr(center, "position"):
            center.position.x = center_x
            center.position.y = center_y
            if hasattr(center.position, "z"):
                center.position.z = 0.0
            if hasattr(center, "orientation"):
                center.orientation.x = 0.0
                center.orientation.y = 0.0
                center.orientation.z = 0.0
                center.orientation.w = 1.0
        else:
            if hasattr(center, "x"):
                center.x = center_x
            if hasattr(center, "y"):
                center.y = center_y

        if hasattr(center, "theta"):
            center.theta = 0.0

    def _throttled_log(
        self,
        key: str,
        level: str,
        message: str,
        period_sec: float = 2.0,
    ) -> None:
        # Rate-limit repeated log messages so transient faults do not spam logs.
        now = time.monotonic()
        last_time = self._log_times.get(key, 0.0)
        if now - last_time < period_sec:
            return

        logger = self.get_logger()
        if level == "error":
            logger.error(message)
        elif level == "info":
            logger.info(message)
        else:
            logger.warn(message)

        self._log_times[key] = now


def main(args: Optional[List[str]] = None) -> None:
    # Start the ROS 2 node and shut it down cleanly on exit.
    rclpy.init(args=args)
    node: Optional[SaakiRos2YoloNode] = None

    try:
        node = SaakiRos2YoloNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        try:
            if rclpy.ok():
                rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
