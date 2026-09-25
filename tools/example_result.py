"""Print an actual canonical result excerpt; same text fixture as test_core."""
import json

import cv2
import numpy as np

from princess_graphology import GraphologyEngine


def example():
    image = np.full((300, 700), 245, np.uint8)
    for i, text in enumerate(['special little princess', 'handwriting analysis', 'deterministic measurements']):
        cv2.putText(image, text, (25, 70 + i * 80), cv2.FONT_HERSHEY_SIMPLEX, 1., 20, 2, cv2.LINE_AA)
    result = GraphologyEngine().analyze(image)
    fields = ('raw_value', 'unit', 'confidence', 'n_observations', 'method_version', 'quality_flag')
    return {key: {field: result.measurements[key].to_dict()[field] for field in fields}
            for key in ('X_HEIGHT_PX', 'WORD_SPACING_REL')}


if __name__ == '__main__':
    print(json.dumps(example(), indent=2, allow_nan=False))
