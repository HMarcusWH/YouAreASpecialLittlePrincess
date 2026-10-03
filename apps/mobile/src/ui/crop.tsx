// Review preview with an optional rectangular crop. The rectangle is drawn on
// the fitted preview and converted to working-image pixels on submit; the
// derivative's frame is what every later coordinate refers to.
import { useEffect, useMemo, useRef, useState } from "react";
import { Image, PanResponder, StyleSheet, View, type LayoutChangeEvent } from "react-native";

import { useApp } from "../bootstrap/AppProvider.tsx";
import type { CropRect, WorkingImage } from "../platform/contracts.ts";
import { previewCropToPixels } from "../work/derivative.ts";

const HANDLE = 44;
const MIN_SIDE = 48;

type Corner = "tl" | "tr" | "bl" | "br";

export function CropView({ image, enabled, maxHeight, onChange, labels }: {
  image: WorkingImage; enabled: boolean; maxHeight: number;
  onChange: (crop: CropRect | null) => void; labels: Record<Corner, string>;
}) {
  const { theme } = useApp();
  const [available, setAvailable] = useState(0);
  const [rect, setRect] = useState<CropRect | null>(null);
  const start = useRef<CropRect | null>(null);
  const box = useMemo(() => {
    if (available === 0) return { width: 0, height: 0 };
    const scale = Math.min(available / image.width, maxHeight / image.height);
    return { width: image.width * scale, height: image.height * scale };
  }, [available, image.width, image.height, maxHeight]);

  // A new working image (for example after rotation) starts uncropped.
  useEffect(() => {
    if (box.width > 0) setRect({ x: 0, y: 0, width: box.width, height: box.height });
  }, [image.uri, box.width, box.height]);

  function layout(event: LayoutChangeEvent) {
    setAvailable(event.nativeEvent.layout.width);
  }

  const responders = useMemo(() => {
    const make = (corner: Corner) => PanResponder.create({
      onStartShouldSetPanResponder: () => enabled,
      onMoveShouldSetPanResponder: () => enabled,
      onPanResponderGrant: () => { start.current = rect; },
      onPanResponderMove: (_event, gesture) => {
        const from = start.current;
        if (!from) return;
        let left = from.x;
        let top = from.y;
        let right = from.x + from.width;
        let bottom = from.y + from.height;
        if (corner === "tl" || corner === "bl") left = Math.min(right - MIN_SIDE, Math.max(0, left + gesture.dx));
        if (corner === "tr" || corner === "br") right = Math.max(left + MIN_SIDE, Math.min(box.width, right + gesture.dx));
        if (corner === "tl" || corner === "tr") top = Math.min(bottom - MIN_SIDE, Math.max(0, top + gesture.dy));
        if (corner === "bl" || corner === "br") bottom = Math.max(top + MIN_SIDE, Math.min(box.height, bottom + gesture.dy));
        const next = { x: left, y: top, width: right - left, height: bottom - top };
        setRect(next);
      },
      onPanResponderRelease: () => {
        start.current = null;
      },
    });
    return { tl: make("tl"), tr: make("tr"), bl: make("bl"), br: make("br") };
  }, [enabled, rect, box]);

  useEffect(() => {
    if (rect === null || box.width === 0) return;
    const full = rect.x <= 0.5 && rect.y <= 0.5 && Math.abs(rect.width - box.width) < 1
      && Math.abs(rect.height - box.height) < 1;
    // Report in working-image pixels; a full-frame rectangle means no crop.
    onChange(full || !enabled ? null : previewCropToPixels(rect, box, image));
    // eslint-disable-next-line react-hooks/exhaustive-deps -- report only when the rectangle or frame changes
  }, [rect, box, enabled]);

  const current = rect;

  return (
    <View onLayout={layout} style={{ width: "100%", alignItems: "center" }}>
      <View style={{ width: box.width, height: box.height }}>
        {box.width > 0 ? <Image source={{ uri: image.uri }} accessibilityIgnoresInvertColors
                                style={{ width: box.width, height: box.height }} /> : null}
        {enabled && current ? (
          <>
            <View pointerEvents="none" style={[local.frame, { left: current.x, top: current.y, width: current.width,
                                                              height: current.height, borderColor: theme.color.accent }]} />
            {(["tl", "tr", "bl", "br"] as const).map((corner) => (
              <View key={corner} accessible accessibilityLabel={labels[corner]} {...responders[corner].panHandlers}
                    style={[local.handle, {
                      left: (corner === "tl" || corner === "bl" ? current.x : current.x + current.width) - HANDLE / 2,
                      top: (corner === "tl" || corner === "tr" ? current.y : current.y + current.height) - HANDLE / 2,
                    }]}>
                <View style={[local.knob, { backgroundColor: theme.color.accent, borderColor: theme.color["accent-contrast"] }]} />
              </View>
            ))}
          </>
        ) : null}
      </View>
    </View>
  );
}

const local = StyleSheet.create({
  frame: { position: "absolute", borderWidth: 2 },
  handle: { position: "absolute", width: HANDLE, height: HANDLE, alignItems: "center", justifyContent: "center" },
  knob: { width: 18, height: 18, borderRadius: 9, borderWidth: 2 },
});
