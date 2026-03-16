import { useMemo } from "react";
import type { SemanticZone } from "../utils/panoramaSemanticMap";

const TILE_SIZE = 2;
const ROOM_PADDING_X = 0.8;
const ROOM_PADDING_BACK = 1.0;
const ROOM_PADDING_FRONT = 0.9;
const ROOM_TOP_Y = 4.2;

type Rotation = [number, number, number];
type PropKind = "counter" | "shelf" | "freezer" | "basket" | "crate";
type PropPlacement = {
  key: string;
  kind: PropKind;
  position: [number, number, number];
  rotation?: Rotation;
  scale?: number;
};

function snapDown(value: number, step: number): number {
  return Math.floor(value / step) * step;
}

function snapUp(value: number, step: number): number {
  return Math.ceil(value / step) * step;
}

function buildTileRange(from: number, to: number): number[] {
  const out: number[] = [];
  for (let value = from; value <= to; value += TILE_SIZE) out.push(value);
  return out;
}

function zoneFrontZ(zone: SemanticZone, inset = 0.68): number {
  return zone.center[2] + zone.size[1] / 2 - inset;
}

function zoneBackZ(zone: SemanticZone, inset = 0.78): number {
  return zone.center[2] - zone.size[1] / 2 + inset;
}

function spanX(zone: SemanticZone, count: number, inset = 0.9): number[] {
  if (count <= 1) return [zone.center[0]];
  const usable = Math.max(0.8, zone.size[0] - inset * 2);
  const step = usable / (count - 1);
  const start = zone.center[0] - usable / 2;
  return Array.from({ length: count }, (_, index) => start + step * index);
}

function CounterDesk({ scale = 1 }: { scale?: number }) {
  return (
    <group scale={scale}>
      <mesh position={[0, 0.28, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.9, 0.56, 0.6]} />
        <meshStandardMaterial color="#64748b" />
      </mesh>
      <mesh position={[0, 0.6, -0.08]} castShadow>
        <boxGeometry args={[0.68, 0.08, 0.18]} />
        <meshStandardMaterial color="#111827" emissive="#0f172a" emissiveIntensity={0.16} />
      </mesh>
      <mesh position={[0, 0.66, 0.12]}>
        <boxGeometry args={[0.28, 0.08, 0.2]} />
        <meshStandardMaterial color="#38bdf8" />
      </mesh>
    </group>
  );
}

function ShelfUnit({ scale = 1 }: { scale?: number }) {
  return (
    <group scale={scale}>
      <mesh position={[0, 0.42, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.82, 0.84, 0.3]} />
        <meshStandardMaterial color="#94a3b8" />
      </mesh>
      <mesh position={[0, 0.84, -0.02]}>
        <boxGeometry args={[0.78, 0.18, 0.08]} />
        <meshStandardMaterial color="#38bdf8" />
      </mesh>
      {[-0.22, 0, 0.22].map((x, index) => (
        <mesh key={`top-${index}`} position={[x, 0.58, 0.1]}>
          <boxGeometry args={[0.12, 0.18, 0.12]} />
          <meshStandardMaterial color="#7dd3fc" />
        </mesh>
      ))}
      {[-0.22, 0, 0.22].map((x, index) => (
        <mesh key={`bottom-${index}`} position={[x, 0.22, 0.08]}>
          <boxGeometry args={[0.16, 0.16, 0.14]} />
          <meshStandardMaterial color="#cbd5e1" />
        </mesh>
      ))}
    </group>
  );
}

function FreezerUnit({ scale = 1 }: { scale?: number }) {
  return (
    <group scale={scale}>
      <mesh position={[0, 0.4, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.86, 0.8, 0.54]} />
        <meshStandardMaterial color="#cbd5e1" />
      </mesh>
      <mesh position={[0, 0.62, 0.2]}>
        <boxGeometry args={[0.74, 0.3, 0.08]} />
        <meshStandardMaterial color="#0ea5e9" emissive="#38bdf8" emissiveIntensity={0.1} />
      </mesh>
    </group>
  );
}

function BasketProp({ scale = 1 }: { scale?: number }) {
  return (
    <group scale={scale}>
      <mesh position={[0, 0.08, 0]} castShadow receiveShadow>
        <boxGeometry args={[0.28, 0.16, 0.2]} />
        <meshStandardMaterial color="#16a34a" />
      </mesh>
      <mesh position={[0, 0.22, 0]}>
        <torusGeometry args={[0.07, 0.012, 8, 16]} />
        <meshStandardMaterial color="#9ca3af" />
      </mesh>
    </group>
  );
}

function FruitCrate({ scale = 1 }: { scale?: number }) {
  return (
    <group scale={scale}>
      <mesh position={[0, 0.1, 0]} castShadow receiveShadow>
        <cylinderGeometry args={[0.26, 0.3, 0.18, 6]} />
        <meshStandardMaterial color="#94a3b8" />
      </mesh>
      {[
        [-0.08, 0.22, -0.04],
        [0.06, 0.23, -0.02],
        [0, 0.26, 0.06],
        [-0.02, 0.2, 0.02],
      ].map((pos, index) => (
        <mesh key={index} position={pos as [number, number, number]}>
          <sphereGeometry args={[0.07, 10, 10]} />
          <meshStandardMaterial color="#38bdf8" />
        </mesh>
      ))}
    </group>
  );
}

function PropInstance({ kind, position, rotation = [0, 0, 0], scale = 1 }: PropPlacement) {
  const content =
    kind === "counter" ? <CounterDesk scale={scale} /> :
    kind === "shelf" ? <ShelfUnit scale={scale} /> :
    kind === "freezer" ? <FreezerUnit scale={scale} /> :
    kind === "basket" ? <BasketProp scale={scale} /> :
    <FruitCrate scale={scale} />;

  return <group position={position} rotation={rotation}>{content}</group>;
}

function zonePlacements(zone: SemanticZone, index: number): PropPlacement[] {
  const front = zoneFrontZ(zone);
  const back = zoneBackZ(zone);
  const left = zone.center[0] - zone.size[0] / 2 + 0.7;
  const right = zone.center[0] + zone.size[0] / 2 - 0.7;

  if (zone.kind === "foreman") {
    return [
      { key: `${zone.id}-desk`, kind: "counter", position: [zone.center[0], 0.02, front - 0.08], scale: 1.05 },
      { key: `${zone.id}-console`, kind: "shelf", position: [zone.center[0], 0.02, back + 0.08], rotation: [0, Math.PI, 0], scale: 0.72 },
    ];
  }

  if (zone.kind === "offline") {
    return [
      // 离线区后排完整留给床位；建筑统一前移，避免继续压到床尾。
      { key: `${zone.id}-freezer`, kind: "freezer", position: [zone.center[0] - 0.42, 0.02, front - 0.04], rotation: [0, Math.PI, 0], scale: 0.88 },
      { key: `${zone.id}-buffer`, kind: "shelf", position: [zone.center[0] + 0.46, 0.02, front - 0.08], rotation: [0, Math.PI, 0], scale: 0.64 },
    ];
  }

  if (zone.kind === "idle") {
    return [
      { key: `${zone.id}-shelf`, kind: "shelf", position: [zone.center[0], 0.02, back + 0.02], rotation: [0, Math.PI / 2, 0], scale: 0.74 },
      { key: `${zone.id}-crate`, kind: "crate", position: [zone.center[0], 0.02, front - 0.12], scale: 0.9 },
    ];
  }

  if (zone.kind === "blocked") {
    return [
      { key: `${zone.id}-left-wall`, kind: "shelf", position: [left + 0.1, 0.02, zone.center[2]], rotation: [0, Math.PI / 2, 0], scale: 0.72 },
      { key: `${zone.id}-right-wall`, kind: "shelf", position: [right - 0.1, 0.02, zone.center[2]], rotation: [0, -Math.PI / 2, 0], scale: 0.72 },
      { key: `${zone.id}-jam-center`, kind: "basket", position: [zone.center[0], 0.02, zone.center[2]], rotation: [0, Math.PI / 6, 0], scale: 0.9 },
    ];
  }

  const shelfCount = zone.size[0] >= 5.2 ? 2 : 1;
  const shelfXs = spanX(zone, shelfCount, 1.2);
  const placements: PropPlacement[] = shelfXs.map((x, shelfIndex) => ({
    key: `${zone.id}-shelf-${shelfIndex}`,
    kind: "shelf",
    position: [x, 0.02, front],
    rotation: [0, index % 2 === 0 ? 0 : Math.PI, 0],
    scale: zone.size[0] >= 5.2 ? 0.72 : 0.68,
  }));

  placements.push(
    { key: `${zone.id}-fruit-left`, kind: "crate", position: [left, 0.02, back + 0.06], rotation: [0, Math.PI / 8, 0], scale: 0.82 },
    { key: `${zone.id}-fruit-right`, kind: "crate", position: [right, 0.02, back + 0.06], rotation: [0, -Math.PI / 8, 0], scale: 0.82 },
  );

  return placements;
}

function FloorTile({ position }: { position: [number, number, number] }) {
  const parity = (Math.round(position[0] / TILE_SIZE) + Math.round(position[2] / TILE_SIZE)) % 2 === 0;
  return (
    <mesh position={position} receiveShadow>
      <boxGeometry args={[TILE_SIZE, 0.08, TILE_SIZE]} />
      <meshStandardMaterial color={parity ? "#e5e7eb" : "#cbd5e1"} />
    </mesh>
  );
}

function WallSegment({ position, rotation = [0, 0, 0], width = TILE_SIZE, color = "#475569" }: {
  position: [number, number, number];
  rotation?: Rotation;
  width?: number;
  color?: string;
}) {
  return (
    <group position={position} rotation={rotation}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[width, 2.4, 0.18]} />
        <meshStandardMaterial color={color} />
      </mesh>
      <mesh position={[0, 0, 0.1]}>
        <boxGeometry args={[width * 0.92, 0.8, 0.04]} />
        <meshStandardMaterial color="#059669" emissive="#059669" emissiveIntensity={0.12} />
      </mesh>
    </group>
  );
}

function ColumnPost({ position }: { position: [number, number, number] }) {
  return (
    <group position={position}>
      <mesh castShadow receiveShadow>
        <boxGeometry args={[0.22, 2.45, 0.22]} />
        <meshStandardMaterial color="#64748b" />
      </mesh>
      <mesh position={[0, 1.1, 0]}>
        <boxGeometry args={[0.12, 0.24, 0.12]} />
        <meshStandardMaterial color="#94a3b8" />
      </mesh>
    </group>
  );
}

function RoomShell({ zones }: { zones: SemanticZone[] }) {
  const shell = useMemo(() => {
    const minX = Math.min(...zones.map((zone) => zone.center[0] - zone.size[0] / 2)) - ROOM_PADDING_X;
    const maxX = Math.max(...zones.map((zone) => zone.center[0] + zone.size[0] / 2)) + ROOM_PADDING_X;
    const minZ = Math.min(...zones.map((zone) => zone.center[2] - zone.size[1] / 2)) - ROOM_PADDING_BACK;
    const maxZ = Math.max(...zones.map((zone) => zone.center[2] + zone.size[1] / 2)) + ROOM_PADDING_FRONT;
    const leftX = snapDown(minX, TILE_SIZE);
    const rightX = snapUp(maxX, TILE_SIZE);
    const backZ = snapDown(minZ, TILE_SIZE);
    const frontZ = Math.max(backZ + TILE_SIZE * 4, snapUp(maxZ - TILE_SIZE / 2, TILE_SIZE));
    const sideWallEndZ = Math.max(backZ + TILE_SIZE * 2, frontZ - TILE_SIZE);
    const centerZ = (backZ + sideWallEndZ) / 2;
    const beamWidth = Math.max(6, rightX - leftX - 0.4);
    const lightWidth = Math.max(5.2, beamWidth - 1.4);
    return {
      leftX,
      rightX,
      backZ,
      frontZ,
      sideWallEndZ,
      centerX: (leftX + rightX) / 2,
      centerZ,
      beamWidth,
      lightWidth,
      floorXs: buildTileRange(leftX, rightX),
      floorZs: buildTileRange(backZ, frontZ),
      wallXs: buildTileRange(leftX, rightX),
      sideWallZs: buildTileRange(backZ + TILE_SIZE, sideWallEndZ),
    };
  }, [zones]);

  const floorTiles: Array<[number, number, number]> = [];
  for (const x of shell.floorXs) {
    for (const z of shell.floorZs) {
      floorTiles.push([x, 0, z]);
    }
  }

  return (
    <group>
      {floorTiles.map((pos, index) => (
        <FloorTile key={`floor-${index}`} position={pos} />
      ))}

      {shell.wallXs.map((x, index) => (
        <WallSegment key={`back-wall-${index}`} position={[x, 1.2, shell.backZ]} width={TILE_SIZE} />
      ))}

      {shell.sideWallZs.map((z, index) => (
        <group key={`side-wall-${index}`}>
          <WallSegment position={[shell.leftX, 1.2, z]} rotation={[0, Math.PI / 2, 0]} width={TILE_SIZE} />
          <WallSegment position={[shell.rightX, 1.2, z]} rotation={[0, -Math.PI / 2, 0]} width={TILE_SIZE} />
        </group>
      ))}

      {[
        [shell.leftX, 1.2, shell.backZ],
        [shell.rightX, 1.2, shell.backZ],
        [shell.leftX, 1.2, shell.sideWallEndZ],
        [shell.rightX, 1.2, shell.sideWallEndZ],
      ].map((pos, index) => (
        <ColumnPost key={`column-${index}`} position={pos as [number, number, number]} />
      ))}

      <mesh position={[shell.centerX, ROOM_TOP_Y, shell.centerZ]}>
        <boxGeometry args={[shell.beamWidth, 0.14, 0.22]} />
        <meshStandardMaterial color="#334155" emissive="#0f172a" emissiveIntensity={0.16} />
      </mesh>
      <mesh position={[shell.centerX, ROOM_TOP_Y - 0.05, shell.centerZ]}>
        <boxGeometry args={[shell.lightWidth, 0.05, 0.05]} />
        <meshStandardMaterial color="#67e8f9" emissive="#67e8f9" emissiveIntensity={0.72} />
      </mesh>
    </group>
  );
}

function ZoneProps({ zones }: { zones: SemanticZone[] }) {
  const placements = zones.flatMap((zone, index) => zonePlacements(zone, index));
  return (
    <group>
      {placements.map((item) => {
        const { key, ...rest } = item;
        return <PropInstance key={key} {...rest} />;
      })}
    </group>
  );
}

export function PanoramaRoom({ zones }: { zones: SemanticZone[] }) {
  return (
    <group>
      <RoomShell zones={zones} />
      <ZoneProps zones={zones} />
    </group>
  );
}
