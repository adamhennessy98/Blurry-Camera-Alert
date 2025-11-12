import random
from typing import Dict, Iterable


class Simulator:
    def __init__(
        self,
        camera_ids: Iterable[str],
        p_blur_on: float = 0.08,
        p_blur_off: float = 0.20,
        auto_clear: bool = False,
    ):
        self.state: Dict[str, bool] = {cid: False for cid in camera_ids}
        self.p_blur_on = p_blur_on
        self.p_blur_off = p_blur_off
        self.auto_clear = auto_clear

    def tick(self) -> Dict[str, bool]:
        for cid in list(self.state.keys()):
            if not self.state[cid]:
                if random.random() < self.p_blur_on:
                    self.state[cid] = True
            else:
                if self.auto_clear and random.random() < self.p_blur_off:
                    self.state[cid] = False
        return self.state.copy()

    def set_blurry(self, camera_id: str, is_blurry: bool) -> None:
        if camera_id in self.state:
            self.state[camera_id] = is_blurry
