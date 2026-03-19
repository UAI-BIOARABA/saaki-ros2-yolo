# Launch file for the saaki_ros2_yolo ROS 2 node.
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description() -> LaunchDescription:
    # Expose the main runtime parameters and start the YOLO node.
    # Use the package's default YAML file unless the caller provides another one.
    default_params_file = PathJoinSubstitution(
        [FindPackageShare("saaki_ros2_yolo"), "config", "yolo_params.yaml"]
    )

    return LaunchDescription(
        [
            # Launch arguments let users override the common tuning parameters
            # without editing the packaged parameter file.
            DeclareLaunchArgument(
                "params_file",
                default_value=default_params_file,
                description="Path to the ROS2 parameters file.",
            ),
            DeclareLaunchArgument(
                "model_path",
                default_value="yolov8n.pt",
                description="YOLO model path or model name.",
            ),
            DeclareLaunchArgument(
                "device",
                default_value="auto",
                description="Inference device. Options: auto, cpu, cuda:0...",
            ),
            DeclareLaunchArgument(
                "target_fps",
                default_value="15.0",
                description="Frame request rate limit in FPS.",
            ),
            DeclareLaunchArgument(
                "annotated_image_max_fps",
                default_value="15.0",
                description="Annotated image publish rate limit in FPS. 0 disables limit.",
            ),
            DeclareLaunchArgument(
                "annotated_image_scale",
                default_value="0.33",
                description="Scale factor applied to annotated image before publish.",
            ),
            Node(
                package="saaki_ros2_yolo",
                executable="saaki_ros2_yolo_node",
                name="saaki_ros2_yolo_node",
                output="screen",
                parameters=[
                    # Load the base YAML file first, then override selected values
                    # with any launch arguments provided by the caller.
                    LaunchConfiguration("params_file"),
                    {
                        "model_path": LaunchConfiguration("model_path"),
                        "device": LaunchConfiguration("device"),
                        "target_fps": LaunchConfiguration("target_fps"),
                        "annotated_image_max_fps": LaunchConfiguration(
                            "annotated_image_max_fps"
                        ),
                        "annotated_image_scale": LaunchConfiguration(
                            "annotated_image_scale"
                        ),
                    },
                ],
            ),
        ]
    )
