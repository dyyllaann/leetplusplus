import { useCallback, useEffect, useRef, useState } from "react";
import type { CapturedFrame } from "@/lib/types";

const MAX_SIDE = 1920;
const JPEG_QUALITY = 0.85;

export function useCamera() {
  const videoRef = useRef<HTMLVideoElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [isActive, setIsActive] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aspectRatio, setAspectRatio] = useState(16 / 9);

  const start = useCallback(async () => {
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "environment", width: { ideal: 1920 }, height: { ideal: 1080 } },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (video) {
        video.srcObject = stream;
        await video.play();
        if (video.videoWidth && video.videoHeight) setAspectRatio(video.videoWidth / video.videoHeight);
      }
      setIsActive(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      throw err;
    }
  }, []);

  const stop = useCallback(() => {
    streamRef.current?.getTracks().forEach((track) => track.stop());
    streamRef.current = null;
    if (videoRef.current) videoRef.current.srcObject = null;
    setIsActive(false);
  }, []);

  useEffect(() => stop, [stop]);

  return { videoRef, isActive, error, aspectRatio, start, stop };
}

/** Grab the current video frame as a downscaled JPEG data URL. */
export function captureFrame(video: HTMLVideoElement, canvas: HTMLCanvasElement): CapturedFrame | null {
  if (!video.videoWidth || !video.videoHeight) return null;
  const scale = Math.min(1, MAX_SIDE / Math.max(video.videoWidth, video.videoHeight));
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d")?.drawImage(video, 0, 0, canvas.width, canvas.height);
  return { capturedAt: new Date().toISOString(), imageData: canvas.toDataURL("image/jpeg", JPEG_QUALITY) };
}
