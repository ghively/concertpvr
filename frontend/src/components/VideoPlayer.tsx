import { useEffect, useRef } from "react";
import { MediaPlayer, MediaOutlet, MediaCommunitySkin } from "@vidstack/react";
import type { MediaPlayerElement } from "vidstack";

export type VideoPlayerHandle = {
  seek: (timeS: number) => void;
  getCurrentTime: () => number;
  play: () => void;
  pause: () => void;
};

interface Props {
  src: string;
  onTimeUpdate?: (timeS: number) => void;
  onDuration?: (durationS: number) => void;
  onReady?: (handle: VideoPlayerHandle) => void;
}

// vidstack 0.6 types use a maverick.js custom element wrapper that doesn't
// cleanly expose its merged members to TypeScript. We cast through unknown to
// access the runtime API (currentTime, play, pause, addEventListener) which
// are verifiably present on the element at runtime.
type PlayerEl = MediaPlayerElement & {
  currentTime: number;
  play: () => Promise<void>;
  pause: () => Promise<void>;
  addEventListener: (type: string, listener: (e: { detail: unknown }) => void) => void;
  removeEventListener: (type: string, listener: (e: { detail: unknown }) => void) => void;
};

export function VideoPlayer({ src, onTimeUpdate, onDuration, onReady }: Props) {
  const elRef = useRef<MediaPlayerElement | null>(null);

  useEffect(() => {
    const el = elRef.current as PlayerEl | null;
    if (!el) return;

    const handleTimeUpdate = (e: { detail: unknown }) => {
      const d = e.detail as { currentTime: number; played: unknown };
      onTimeUpdate?.(d.currentTime);
    };
    const handleDurationChange = (e: { detail: unknown }) => {
      const v = e.detail as number;
      onDuration?.(v);
    };

    el.addEventListener("time-update", handleTimeUpdate);
    el.addEventListener("duration-change", handleDurationChange);

    if (onReady) {
      onReady({
        seek: (s) => { el.currentTime = s; },
        getCurrentTime: () => el.currentTime,
        play: () => { void el.play(); },
        pause: () => { void el.pause(); },
      });
    }

    return () => {
      el.removeEventListener("time-update", handleTimeUpdate);
      el.removeEventListener("duration-change", handleDurationChange);
    };
  // onTimeUpdate/onDuration/onReady are intentionally captured at mount
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="aspect-video w-full bg-black">
      <MediaPlayer
        ref={elRef}
        src={src}
        playsInline
      >
        <MediaOutlet />
        <MediaCommunitySkin />
      </MediaPlayer>
    </div>
  );
}
