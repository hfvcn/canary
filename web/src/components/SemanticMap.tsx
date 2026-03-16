import { useEffect, useMemo } from "react";
import * as THREE from "three";
import type { SemanticZone } from "../utils/panoramaSemanticMap";

interface SemanticMapProps {
  zones: SemanticZone[];
  isDark: boolean;
  compact?: boolean;
  projectStatus?: string | null;
}

function zoneAnchorPosition(zone: SemanticZone): [number, number, number] {
  const halfWidth = zone.size[0] / 2;
  const halfDepth = zone.size[1] / 2;
  const sideInset = Math.min(0.56, halfWidth * 0.45);
  const edgeInset = Math.min(0.52, halfDepth * 0.45);

  // 将分区图标贴到区域边缘，避免与区域中部的人物站位重合。
  switch (zone.kind) {
    case "blocked":
      return [zone.center[0] - halfWidth + sideInset, 0, zone.center[2] - halfDepth + edgeInset];
    case "foreman":
      return [zone.center[0] + halfWidth - sideInset, 0, zone.center[2] - halfDepth + edgeInset];
    case "idle":
      return [zone.center[0] - halfWidth + sideInset, 0, zone.center[2] + halfDepth - edgeInset];
    case "offline":
      return [zone.center[0] + halfWidth - sideInset, 0, zone.center[2] + halfDepth - edgeInset];
    case "task":
    default:
      return [zone.center[0], 0, zone.center[2] - halfDepth + edgeInset];
  }
}

function ZoneLabel({ primary, secondary, color, isDark, compact = false, position }: {
  primary: string;
  secondary?: string;
  color: string;
  isDark: boolean;
  compact?: boolean;
  position: [number, number, number];
}) {
  const labelState = useMemo(() => {
    const dpr = 2;
    const primaryFs = (compact ? 9 : 11) * dpr;
    const secondaryFs = (compact ? 0 : 8) * dpr;
    const canvas = document.createElement("canvas");
    const measure = canvas.getContext("2d")!;
    measure.font = `700 ${primaryFs}px sans-serif`;
    const primaryWidth = measure.measureText(primary).width;
    measure.font = `500 ${secondaryFs}px sans-serif`;
    const secondaryText = compact ? undefined : secondary;
    const secondaryWidth = secondaryText ? measure.measureText(secondaryText).width : 0;
    const padX = 14 * dpr;
    const padY = 8 * dpr;
    const width = Math.ceil(Math.max(primaryWidth, secondaryWidth) + padX * 2);
    const height = Math.ceil(primaryFs + (secondaryText ? secondaryFs + 6 * dpr : 0) + padY * 2);
    canvas.width = width;
    canvas.height = height;
    const ctx = canvas.getContext("2d")!;

    ctx.beginPath();
    ctx.roundRect(0, 0, width, height, 8 * dpr);
    ctx.fillStyle = isDark ? "rgba(15,23,42,0.82)" : "rgba(255,255,255,0.92)";
    ctx.fill();

    ctx.strokeStyle = color;
    ctx.lineWidth = 2 * dpr;
    ctx.stroke();

    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `700 ${primaryFs}px sans-serif`;
    ctx.fillStyle = isDark ? "#f8fafc" : "#0f172a";
    ctx.fillText(primary, width / 2, secondaryText ? height / 2 - 8 * dpr : height / 2);

    if (secondaryText) {
      ctx.font = `500 ${secondaryFs}px sans-serif`;
      ctx.fillStyle = isDark ? "#cbd5e1" : "#475569";
      ctx.fillText(secondaryText, width / 2, height / 2 + 11 * dpr);
    }

    const tex = new THREE.CanvasTexture(canvas);
    tex.colorSpace = THREE.SRGBColorSpace;
    const baseWorldW = compact ? width / dpr / 120 : width / dpr / 95;
    const worldW = Math.max(compact ? 0.82 : 1.1, Math.min(compact ? 1.45 : 2.2, baseWorldW));
    return { tex, scale: [worldW, worldW * (height / width)] as [number, number] };
  }, [primary, secondary, color, compact, isDark]);

  useEffect(() => () => { labelState.tex.dispose(); }, [labelState.tex]);

  return (
    <sprite position={position} scale={[labelState.scale[0], labelState.scale[1], 1]}>
      <spriteMaterial map={labelState.tex} transparent depthWrite={false} />
    </sprite>
  );
}

function StatusBanner({ text, isDark, compact = false }: { text: string; isDark: boolean; compact?: boolean }) {
  return (
    <ZoneLabel
      primary={text}
      color={isDark ? "#38bdf8" : "#2563eb"}
      isDark={isDark}
      compact={compact}
      position={[0, compact ? 0.62 : 0.7, 8.7]}
    />
  );
}

function ZoneAnchor({ zone, isDark, compact = false }: { zone: SemanticZone; isDark: boolean; compact?: boolean }) {
  const accent = zone.color;
  const base = isDark ? "#0f172a" : "#ffffff";
  const anchorPosition = zoneAnchorPosition(zone);

  return (
    <group position={anchorPosition}>
      {/* 轻量锚点：保留分区提示，但不再用整块地板染色 */}
      <mesh position={[0, 0.035, 0]}>
        <cylinderGeometry args={[0.26, 0.26, 0.04, 18]} />
        <meshStandardMaterial color={base} transparent opacity={0.9} />
      </mesh>
      <mesh position={[0, 0.06, 0]}>
        <cylinderGeometry args={[0.14, 0.14, 0.02, 18]} />
        <meshStandardMaterial color={accent} emissive={accent} emissiveIntensity={0.16} />
      </mesh>
      <ZoneLabel
        primary={zone.label}
        secondary={compact ? undefined : zone.subtitle}
        color={zone.color}
        isDark={isDark}
        compact={compact}
        position={[0, compact ? 0.62 : 0.72, 0]}
      />
    </group>
  );
}

export function SemanticMap({ zones, isDark, compact = false, projectStatus }: SemanticMapProps) {
  return (
    <>
      {zones.map((zone) => (
        <ZoneAnchor key={zone.id} zone={zone} isDark={isDark} compact={compact} />
      ))}
      {projectStatus ? <StatusBanner text={projectStatus} isDark={isDark} compact={compact} /> : null}
    </>
  );
}
