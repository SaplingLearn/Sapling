"use client";

import React from "react";
import type { Cosmetic } from "@/lib/types";
import { Avatar } from "@/components/Avatar";

interface AvatarFrameProps {
  name: string;
  size?: number;
  img?: string;
  color?: string;
  frame?: Cosmetic | null;
}

export function AvatarFrame({ name, size = 48, img, color, frame }: AvatarFrameProps) {
  const overlay = size * 0.25;
  return (
    <div style={{ position: "relative", width: size + overlay, height: size + overlay, display: "inline-block" }}>
      <div style={{ position: "absolute", top: overlay / 2, left: overlay / 2 }}>
        <Avatar name={name} size={size} img={img} color={color} />
      </div>
      {frame?.asset_url && (
        <img
          src={frame.asset_url}
          alt=""
          aria-hidden
          referrerPolicy="no-referrer"
          style={{
            position: "absolute",
            inset: 0,
            width: "100%",
            height: "100%",
            pointerEvents: "none",
            objectFit: "contain",
          }}
        />
      )}
    </div>
  );
}
