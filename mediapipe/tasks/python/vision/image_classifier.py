# Copyright 2022 The MediaPipe Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""MediaPipe image classifier task."""

import dataclasses
from typing import Callable, Mapping, Optional

from mediapipe.python import packet_creator
from mediapipe.python import packet_getter
# TODO: Import MPImage directly one we have an alias
from mediapipe.python._framework_bindings import image as image_module
from mediapipe.python._framework_bindings import packet
from mediapipe.tasks.cc.components.containers.proto import classifications_pb2
from mediapipe.tasks.cc.vision.image_classifier.proto import image_classifier_graph_options_pb2
from mediapipe.tasks.python.components.containers import classifications
from mediapipe.tasks.python.components.containers import rect
from mediapipe.tasks.python.components.processors import classifier_options
from mediapipe.tasks.python.core import base_options as base_options_module
from mediapipe.tasks.python.core import task_info as task_info_module
from mediapipe.tasks.python.core.optional_dependencies import doc_controls
from mediapipe.tasks.python.vision.core import base_vision_task_api
from mediapipe.tasks.python.vision.core import vision_task_running_mode

_NormalizedRect = rect.NormalizedRect
_BaseOptions = base_options_module.BaseOptions
_ImageClassifierGraphOptionsProto = image_classifier_graph_options_pb2.ImageClassifierGraphOptions
_ClassifierOptions = classifier_options.ClassifierOptions
_RunningMode = vision_task_running_mode.VisionTaskRunningMode
_TaskInfo = task_info_module.TaskInfo

_CLASSIFICATION_RESULT_OUT_STREAM_NAME = 'classification_result_out'
_CLASSIFICATION_RESULT_TAG = 'CLASSIFICATION_RESULT'
_IMAGE_IN_STREAM_NAME = 'image_in'
_IMAGE_OUT_STREAM_NAME = 'image_out'
_IMAGE_TAG = 'IMAGE'
_NORM_RECT_NAME = 'norm_rect_in'
_NORM_RECT_TAG = 'NORM_RECT'
_TASK_GRAPH_NAME = 'mediapipe.tasks.vision.image_classifier.ImageClassifierGraph'
_MICRO_SECONDS_PER_MILLISECOND = 1000


def _build_full_image_norm_rect() -> _NormalizedRect:
  # Builds a NormalizedRect covering the entire image.
  return _NormalizedRect(x_center=0.5, y_center=0.5, width=1, height=1)


@dataclasses.dataclass
class ImageClassifierOptions:
  """Options for the image classifier task.

  Attributes:
    base_options: Base options for the image classifier task.
    running_mode: The running mode of the task. Default to the image mode. Image
      classifier task has three running modes: 1) The image mode for classifying
      objects on single image inputs. 2) The video mode for classifying objects
      on the decoded frames of a video. 3) The live stream mode for classifying
      objects on a live stream of input data, such as from camera.
    classifier_options: Options for the image classification task.
    result_callback: The user-defined result callback for processing live stream
      data. The result callback should only be specified when the running mode
      is set to the live stream mode.
  """
  base_options: _BaseOptions
  running_mode: _RunningMode = _RunningMode.IMAGE
  classifier_options: _ClassifierOptions = _ClassifierOptions()
  result_callback: Optional[
      Callable[[classifications.ClassificationResult, image_module.Image, int],
               None]] = None

  @doc_controls.do_not_generate_docs
  def to_pb2(self) -> _ImageClassifierGraphOptionsProto:
    """Generates an ImageClassifierOptions protobuf object."""
    base_options_proto = self.base_options.to_pb2()
    base_options_proto.use_stream_mode = False if self.running_mode == _RunningMode.IMAGE else True
    classifier_options_proto = self.classifier_options.to_pb2()

    return _ImageClassifierGraphOptionsProto(
        base_options=base_options_proto,
        classifier_options=classifier_options_proto)


class ImageClassifier(base_vision_task_api.BaseVisionTaskApi):
  """Class that performs image classification on images."""

  @classmethod
  def create_from_model_path(cls, model_path: str) -> 'ImageClassifier':
    """Creates an `ImageClassifier` object from a TensorFlow Lite model and the default `ImageClassifierOptions`.

    Note that the created `ImageClassifier` instance is in image mode, for
    classifying objects on single image inputs.

    Args:
      model_path: Path to the model.

    Returns:
      `ImageClassifier` object that's created from the model file and the
      default `ImageClassifierOptions`.

    Raises:
      ValueError: If failed to create `ImageClassifier` object from the provided
        file such as invalid file path.
      RuntimeError: If other types of error occurred.
    """
    base_options = _BaseOptions(model_asset_path=model_path)
    options = ImageClassifierOptions(
        base_options=base_options, running_mode=_RunningMode.IMAGE)
    return cls.create_from_options(options)

  @classmethod
  def create_from_options(cls,
                          options: ImageClassifierOptions) -> 'ImageClassifier':
    """Creates the `ImageClassifier` object from image classifier options.

    Args:
      options: Options for the image classifier task.

    Returns:
      `ImageClassifier` object that's created from `options`.

    Raises:
      ValueError: If failed to create `ImageClassifier` object from
        `ImageClassifierOptions` such as missing the model.
      RuntimeError: If other types of error occurred.
    """

    def packets_callback(output_packets: Mapping[str, packet.Packet]):
      if output_packets[_IMAGE_OUT_STREAM_NAME].is_empty():
        return

      classification_result_proto = classifications_pb2.ClassificationResult()
      classification_result_proto.CopyFrom(
          packet_getter.get_proto(
              output_packets[_CLASSIFICATION_RESULT_OUT_STREAM_NAME]))

      classification_result = classifications.ClassificationResult([
          classifications.Classifications.create_from_pb2(classification)
          for classification in classification_result_proto.classifications
      ])
      image = packet_getter.get_image(output_packets[_IMAGE_OUT_STREAM_NAME])
      timestamp = output_packets[_IMAGE_OUT_STREAM_NAME].timestamp
      options.result_callback(classification_result, image,
                              timestamp.value // _MICRO_SECONDS_PER_MILLISECOND)

    task_info = _TaskInfo(
        task_graph=_TASK_GRAPH_NAME,
        input_streams=[
            ':'.join([_IMAGE_TAG, _IMAGE_IN_STREAM_NAME]),
            ':'.join([_NORM_RECT_TAG, _NORM_RECT_NAME]),
        ],
        output_streams=[
            ':'.join([
                _CLASSIFICATION_RESULT_TAG,
                _CLASSIFICATION_RESULT_OUT_STREAM_NAME
            ]), ':'.join([_IMAGE_TAG, _IMAGE_OUT_STREAM_NAME])
        ],
        task_options=options)
    return cls(
        task_info.generate_graph_config(
            enable_flow_limiting=options.running_mode ==
            _RunningMode.LIVE_STREAM), options.running_mode,
        packets_callback if options.result_callback else None)

  # TODO: Replace _NormalizedRect with ImageProcessingOption
  def classify(
      self,
      image: image_module.Image,
      roi: Optional[_NormalizedRect] = None
  ) -> classifications.ClassificationResult:
    """Performs image classification on the provided MediaPipe Image.

    Args:
      image: MediaPipe Image.
      roi: The region of interest.

    Returns:
      A classification result object that contains a list of classifications.

    Raises:
      ValueError: If any of the input arguments is invalid.
      RuntimeError: If image classification failed to run.
    """
    norm_rect = roi if roi is not None else _build_full_image_norm_rect()
    output_packets = self._process_image_data({
        _IMAGE_IN_STREAM_NAME: packet_creator.create_image(image),
        _NORM_RECT_NAME: packet_creator.create_proto(norm_rect.to_pb2())
    })

    classification_result_proto = classifications_pb2.ClassificationResult()
    classification_result_proto.CopyFrom(
        packet_getter.get_proto(
            output_packets[_CLASSIFICATION_RESULT_OUT_STREAM_NAME]))

    return classifications.ClassificationResult([
        classifications.Classifications.create_from_pb2(classification)
        for classification in classification_result_proto.classifications
    ])

  def classify_for_video(
      self,
      image: image_module.Image,
      timestamp_ms: int,
      roi: Optional[_NormalizedRect] = None
  ) -> classifications.ClassificationResult:
    """Performs image classification on the provided video frames.

    Only use this method when the ImageClassifier is created with the video
    running mode. It's required to provide the video frame's timestamp (in
    milliseconds) along with the video frame. The input timestamps should be
    monotonically increasing for adjacent calls of this method.

    Args:
      image: MediaPipe Image.
      timestamp_ms: The timestamp of the input video frame in milliseconds.
      roi: The region of interest.

    Returns:
      A classification result object that contains a list of classifications.

    Raises:
      ValueError: If any of the input arguments is invalid.
      RuntimeError: If image classification failed to run.
    """
    norm_rect = roi if roi is not None else _build_full_image_norm_rect()
    output_packets = self._process_video_data({
        _IMAGE_IN_STREAM_NAME:
            packet_creator.create_image(image).at(
                timestamp_ms * _MICRO_SECONDS_PER_MILLISECOND),
        _NORM_RECT_NAME:
            packet_creator.create_proto(norm_rect.to_pb2()).at(
                timestamp_ms * _MICRO_SECONDS_PER_MILLISECOND)
    })

    classification_result_proto = classifications_pb2.ClassificationResult()
    classification_result_proto.CopyFrom(
        packet_getter.get_proto(
            output_packets[_CLASSIFICATION_RESULT_OUT_STREAM_NAME]))

    return classifications.ClassificationResult([
        classifications.Classifications.create_from_pb2(classification)
        for classification in classification_result_proto.classifications
    ])

  def classify_async(self,
                     image: image_module.Image,
                     timestamp_ms: int,
                     roi: Optional[_NormalizedRect] = None) -> None:
    """Sends live image data (an Image with a unique timestamp) to perform image classification.

    Only use this method when the ImageClassifier is created with the live
    stream running mode. The input timestamps should be monotonically increasing
    for adjacent calls of this method. This method will return immediately after
    the input image is accepted. The results will be available via the
    `result_callback` provided in the `ImageClassifierOptions`. The
    `classify_async` method is designed to process live stream data such as
    camera input. To lower the overall latency, image classifier may drop the
    input images if needed. In other words, it's not guaranteed to have output
    per input image.

    The `result_callback` provides:
      - A classification result object that contains a list of classifications.
      - The input image that the image classifier runs on.
      - The input timestamp in milliseconds.

    Args:
      image: MediaPipe Image.
      timestamp_ms: The timestamp of the input image in milliseconds.
      roi: The region of interest.

    Raises:
      ValueError: If the current input timestamp is smaller than what the image
        classifier has already processed.
    """
    norm_rect = roi if roi is not None else _build_full_image_norm_rect()
    self._send_live_stream_data({
        _IMAGE_IN_STREAM_NAME:
            packet_creator.create_image(image).at(
                timestamp_ms * _MICRO_SECONDS_PER_MILLISECOND),
        _NORM_RECT_NAME:
            packet_creator.create_proto(norm_rect.to_pb2()).at(
                timestamp_ms * _MICRO_SECONDS_PER_MILLISECOND)
    })
