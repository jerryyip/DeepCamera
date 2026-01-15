from dataclasses import dataclass
from typing import Optional, Tuple

from hailo_platform import (
    HEF,
    ConfigureParams,
    FormatType,
    HailoStreamInterface,
    InputVStreamParams,
    InputVStreams,
    OutputVStreamParams,
    OutputVStreams,
    VDevice,
)


@dataclass(frozen=True)
class TensorInfo:
    name: str
    shape: Optional[Tuple[int, ...]]


class HailoInferenceSession:
    def __init__(self, hef_path, interface=HailoStreamInterface.PCIe):
        self.hef = HEF(hef_path)
        self.device = VDevice()
        self.configure_params = ConfigureParams.create_from_hef(self.hef, interface=interface)
        self.network_group = self.device.configure(self.hef, self.configure_params)[0]
        self.network_group_params = self.network_group.create_params()
        self.input_vstream_infos = self.network_group.get_input_vstream_infos()
        self.output_vstream_infos = self.network_group.get_output_vstream_infos()
        self.input_names = [info.name for info in self.input_vstream_infos]
        self.output_names = [info.name for info in self.output_vstream_infos]
        self.input_vstreams_params = InputVStreamParams.make(
            self.network_group, quantized=False, format_type=FormatType.FLOAT32
        )
        self.output_vstreams_params = OutputVStreamParams.make(
            self.network_group, quantized=False, format_type=FormatType.FLOAT32
        )

    def get_inputs(self):
        return [
            TensorInfo(name=info.name, shape=self._extract_shape(info))
            for info in self.input_vstream_infos
        ]

    def get_outputs(self):
        return [
            TensorInfo(name=info.name, shape=self._extract_shape(info))
            for info in self.output_vstream_infos
        ]

    def run(self, output_names, inputs):
        input_data = [inputs[name] for name in self.input_names]
        outputs = []
        with self.network_group.activate(self.network_group_params):
            with InputVStreams(self.network_group, self.input_vstreams_params) as input_vstreams, \
                OutputVStreams(self.network_group, self.output_vstreams_params) as output_vstreams:
                for vstream, data in zip(input_vstreams, input_data):
                    vstream.send(data)
                for vstream in output_vstreams:
                    outputs.append(vstream.recv())
        if output_names is None:
            return outputs
        output_map = dict(zip(self.output_names, outputs))
        return [output_map[name] for name in output_names]

    @staticmethod
    def _extract_shape(info):
        for attr in ("shape", "hw_shape", "logical_shape"):
            if hasattr(info, attr):
                shape = getattr(info, attr)
                if shape is not None:
                    return tuple(shape)
        return None
