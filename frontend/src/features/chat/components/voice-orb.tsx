"use client";

import { useEffect, useRef, type FC } from "react";

export type VoiceOrbState = "connecting" | "listening" | "speaking" | "muted";

export type VoiceOrbProps = {
  state: VoiceOrbState;
  volume: number;
};

type OrbPalette = {
  top: string;
  middle: string;
  accent: string;
  glow: string;
};

const ORB_PALETTES: Record<VoiceOrbState, OrbPalette> = {
  connecting: {
    top: "#8c67f6",
    middle: "#ad91fb",
    accent: "#ded4ff",
    glow: "rgba(126, 91, 245, 0.24)",
  },
  listening: {
    top: "#7444ef",
    middle: "#9368f8",
    accent: "#d4c4ff",
    glow: "rgba(112, 72, 238, 0.32)",
  },
  speaking: {
    top: "#5d5cf2",
    middle: "#8177fb",
    accent: "#c9ccff",
    glow: "rgba(84, 85, 236, 0.38)",
  },
  muted: {
    top: "#aaa4bc",
    middle: "#c1bbcf",
    accent: "#e7e3ed",
    glow: "rgba(125, 119, 145, 0.18)",
  },
};

export const VoiceOrb: FC<VoiceOrbProps> = ({ state, volume }) => {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stateRef = useRef(state);
  const volumeRef = useRef(volume);
  stateRef.current = state;
  volumeRef.current = volume;

  useEffect(() => {
    const canvas = canvasRef.current;
    if (canvas === null) return;
    const context = canvas.getContext("2d");
    if (context === null) return;

    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let width = 0;
    let height = 0;
    let pixelRatio = 1;
    let animationFrame = 0;

    const resize = (): void => {
      const bounds = canvas.getBoundingClientRect();
      width = bounds.width;
      height = bounds.height;
      pixelRatio = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.max(1, Math.round(width * pixelRatio));
      canvas.height = Math.max(1, Math.round(height * pixelRatio));
    };

    const draw = (timestamp: number): void => {
      const time = reducedMotion ? 0 : timestamp / 1000;
      const palette = ORB_PALETTES[stateRef.current];
      const inputVolume = Math.min(1, Math.max(0, volumeRef.current));
      const stateEnergy = stateRef.current === "speaking" ? 0.24 : 0.08;
      const energy = Math.min(1, stateEnergy + inputVolume * 0.9);
      const centerX = width / 2;
      const centerY = height / 2;
      const radius = Math.min(width, height) * 0.496;

      context.setTransform(1, 0, 0, 1, 0, 0);
      context.clearRect(0, 0, canvas.width, canvas.height);
      context.setTransform(pixelRatio, 0, 0, pixelRatio, 0, 0);
      context.save();
      context.beginPath();
      context.arc(centerX, centerY, radius, 0, Math.PI * 2);
      context.clip();

      const base = context.createLinearGradient(0, centerY - radius, 0, centerY + radius);
      base.addColorStop(0, palette.top);
      base.addColorStop(0.35, palette.middle);
      base.addColorStop(0.58, palette.accent);
      base.addColorStop(1, "#fbf9ff");
      context.fillStyle = base;
      context.fillRect(centerX - radius, centerY - radius, radius * 2, radius * 2);

      const waveBase = centerY + radius * (0.06 - energy * 0.12);
      const waveAmplitude = radius * (0.055 + energy * 0.075);
      const getWaveY = (progress: number): number =>
        waveBase +
        Math.sin(progress * Math.PI * 3.1 + time * 1.12) * waveAmplitude +
        Math.sin(progress * Math.PI * 6.3 - time * 0.72) * waveAmplitude * 0.32;
      context.save();
      context.filter = `blur(${radius * 0.085}px)`;
      context.beginPath();
      context.moveTo(centerX - radius * 1.25, centerY + radius * 1.3);
      for (let index = 0; index <= 64; index += 1) {
        const progress = index / 64;
        const x = centerX - radius * 1.25 + progress * radius * 2.5;
        context.lineTo(x, getWaveY(progress));
      }
      context.lineTo(centerX + radius * 1.25, centerY + radius * 1.3);
      context.closePath();
      const milk = context.createLinearGradient(0, waveBase - waveAmplitude, 0, centerY + radius);
      milk.addColorStop(0, "rgba(255, 255, 255, 0.82)");
      milk.addColorStop(0.38, "rgba(251, 248, 255, 0.96)");
      milk.addColorStop(1, "rgba(247, 243, 255, 1)");
      context.fillStyle = milk;
      context.fill();
      context.restore();

      context.save();
      for (let index = 0; index < 150; index += 1) {
        const progress = fractional(Math.sin(index * 12.9898) * 43758.5453);
        const offset = fractional(Math.sin(index * 78.233) * 24634.6345) - 0.5;
        const particleX = centerX - radius * 1.03 + progress * radius * 2.06;
        const particleY = getWaveY(progress) + offset * radius * 0.22;
        const particleRadius = 0.25 + fractional(Math.sin(index * 43.17) * 15731.743) * 0.55;
        context.globalAlpha = 0.035 + (0.5 - Math.abs(offset)) * 0.16;
        context.fillStyle = offset < 0 ? palette.accent : "#ffffff";
        context.beginPath();
        context.arc(particleX, particleY, particleRadius, 0, Math.PI * 2);
        context.fill();
      }
      context.restore();

      context.restore();

      context.save();
      context.strokeStyle = "rgba(255,255,255,0.7)";
      context.lineWidth = 1;
      context.beginPath();
      context.arc(centerX, centerY, radius - 0.5, 0, Math.PI * 2);
      context.stroke();
      context.restore();

      if (!reducedMotion) animationFrame = requestAnimationFrame(draw);
    };

    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(canvas);
    animationFrame = requestAnimationFrame(draw);

    return () => {
      resizeObserver.disconnect();
      cancelAnimationFrame(animationFrame);
    };
  }, []);

  const normalizedVolume = Math.min(1, Math.max(0, volume));
  const volumeScale = 1 + normalizedVolume * 0.09;

  return (
    <div
      aria-hidden="true"
      className="voice-orb-stage"
      data-state={state}
      style={{ transform: `scale(${volumeScale})` }}
    >
      <span className="voice-orb-aura" style={{ background: ORB_PALETTES[state].glow }} />
      <span className="voice-orb-shell">
        <canvas ref={canvasRef} className="size-full" />
      </span>
    </div>
  );
};

function fractional(value: number): number {
  return value - Math.floor(value);
}
