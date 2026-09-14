import React, { Suspense, useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { wrap360 } from '../../utils/format.js';

function lerp(a, b, t) {
  return a + (b - a) * t;
}

function degToRad(d) {
  return (d * Math.PI) / 180;
}

/** Procedural rocket: cone nose + cylinder body + fins. */
function RocketMesh() {
  return (
    <group>
      <mesh position={[0, 0.55, 0]}>
        <coneGeometry args={[0.22, 0.45, 16]} />
        <meshStandardMaterial color="#f0733d" metalness={0.35} roughness={0.45} />
      </mesh>
      <mesh position={[0, 0, 0]}>
        <cylinderGeometry args={[0.22, 0.24, 0.9, 16]} />
        <meshStandardMaterial color="#d8dee8" metalness={0.4} roughness={0.4} />
      </mesh>
      <mesh position={[0, -0.55, 0]}>
        <cylinderGeometry args={[0.18, 0.28, 0.2, 12]} />
        <meshStandardMaterial color="#3d4a5c" metalness={0.2} roughness={0.7} />
      </mesh>
      {/* Fins */}
      {[0, 90, 180, 270].map((a) => (
        <mesh
          key={a}
          position={[
            0.22 * Math.sin(degToRad(a)),
            -0.35,
            0.22 * Math.cos(degToRad(a)),
          ]}
          rotation={[0, degToRad(a), 0]}
        >
          <boxGeometry args={[0.04, 0.28, 0.32]} />
          <meshStandardMaterial color="#3d9cf0" metalness={0.3} roughness={0.5} />
        </mesh>
      ))}
      {/* Axis helper nose tint */}
      <mesh position={[0, 0.85, 0]}>
        <sphereGeometry args={[0.05, 8, 8]} />
        <meshStandardMaterial color="#7dffb3" emissive="#1a5c3a" />
      </mesh>
    </group>
  );
}

/** Procedural cubesat + solar panels. */
function SatelliteMesh() {
  return (
    <group>
      <mesh>
        <boxGeometry args={[0.55, 0.55, 0.55]} />
        <meshStandardMaterial color="#c5cdd8" metalness={0.5} roughness={0.35} />
      </mesh>
      {/* Solar panels */}
      <mesh position={[-0.7, 0, 0]}>
        <boxGeometry args={[0.7, 0.08, 0.45]} />
        <meshStandardMaterial color="#1e4d8c" metalness={0.6} roughness={0.25} />
      </mesh>
      <mesh position={[0.7, 0, 0]}>
        <boxGeometry args={[0.7, 0.08, 0.45]} />
        <meshStandardMaterial color="#1e4d8c" metalness={0.6} roughness={0.25} />
      </mesh>
      {/* Antenna */}
      <mesh position={[0, 0.45, 0]}>
        <cylinderGeometry args={[0.02, 0.02, 0.35, 8]} />
        <meshStandardMaterial color="#3dd6a5" />
      </mesh>
    </group>
  );
}

/**
 * Vehicle body that lerps toward store pitch/yaw/roll each frame
 * to avoid visual jitter between ~16 fps WS updates (PRD C.4).
 */
function AttitudeBody({ vehicle, vehicleKind }) {
  const group = useRef();
  const target = useRef({ pitch: 0, yaw: 0, roll: 0 });
  const smooth = useRef({ pitch: 0, yaw: 0, roll: 0 });

  const useStore = useVehicleStore(vehicle);
  // Subscribe outside useFrame via zustand — values update React render
  // and we copy into target ref for the rAF loop.
  const pitch = useStore((s) => s.telemetry.pitch) ?? 0;
  const yaw = useStore((s) => s.telemetry.yaw) ?? 0;
  const roll = useStore((s) => s.telemetry.roll) ?? 0;

  target.current = { pitch, yaw: wrap360(yaw), roll };

  useFrame((_, dt) => {
    if (!group.current) return;
    const k = 1 - Math.exp(-8 * Math.min(dt, 0.05));
    const s = smooth.current;
    const t = target.current;

    // Shortest-path yaw lerp
    let dy = t.yaw - s.yaw;
    if (dy > 180) dy -= 360;
    if (dy < -180) dy += 360;
    s.pitch = lerp(s.pitch, t.pitch, k);
    s.yaw = wrap360(s.yaw + dy * k);
    s.roll = lerp(s.roll, t.roll, k);

    // Aerospace: yaw (Y), pitch (X), roll (Z) — visual convention for upright model
    group.current.rotation.order = 'YXZ';
    group.current.rotation.y = degToRad(s.yaw);
    group.current.rotation.x = degToRad(-s.pitch);
    group.current.rotation.z = degToRad(-s.roll);
  });

  const mesh = useMemo(
    () => (vehicleKind === 'satellite' ? <SatelliteMesh /> : <RocketMesh />),
    [vehicleKind]
  );

  return <group ref={group}>{mesh}</group>;
}

function Fallback() {
  return (
    <div className="body3d-fallback">
      3D view unavailable
    </div>
  );
}

/**
 * 3D tilt/body animation via react-three-fiber (PRD G6 / C.4).
 */
export default function Body3D({ vehicle }) {
  const vehicleKind = vehicle === 'satellite' ? 'satellite' : 'rocket';
  const accent = vehicleKind === 'satellite' ? '#3dd6a5' : '#f0733d';

  return (
    <div className="body3d-panel" aria-label="3D attitude">
      <div className="panel-title">3D body</div>
      <div className="body3d-canvas-wrap">
        <Suspense fallback={<Fallback />}>
          <Canvas
            dpr={[1, 1.5]}
            camera={{ position: [1.6, 1.1, 2.2], fov: 42 }}
            gl={{ antialias: true, alpha: true, powerPreference: 'low-power' }}
            onCreated={({ gl }) => {
              gl.setClearColor('#0b0f14', 0);
            }}
          >
            <ambientLight intensity={0.55} />
            <directionalLight position={[3, 4, 2]} intensity={1.1} color="#ffffff" />
            <directionalLight position={[-2, -1, -2]} intensity={0.35} color={accent} />
            <AttitudeBody vehicle={vehicle} vehicleKind={vehicleKind} />
            <gridHelper args={[4, 8, '#1e2a38', '#15202c']} position={[0, -0.9, 0]} />
          </Canvas>
        </Suspense>
      </div>
      <div className="body3d-caption muted small">
        {vehicleKind === 'satellite' ? 'CubeSat model' : 'Rocket model'} · live pitch/yaw/roll
      </div>
    </div>
  );
}
