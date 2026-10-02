import React, { Component, Suspense, useMemo, useRef } from 'react';
import { Canvas, useFrame } from '@react-three/fiber';
import { OrbitControls, useGLTF } from '@react-three/drei';
import * as THREE from 'three';
import { useVehicleStore } from '../../state/vehicleStore.js';
import { wrap360 } from '../../utils/format.js';

const CAD_URL = {
  rocket: `${import.meta.env.BASE_URL}models/rocket.glb`,
  satellite: `${import.meta.env.BASE_URL}models/cansat.glb`,
};

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
      <mesh position={[-0.7, 0, 0]}>
        <boxGeometry args={[0.7, 0.08, 0.45]} />
        <meshStandardMaterial color="#1e4d8c" metalness={0.6} roughness={0.25} />
      </mesh>
      <mesh position={[0.7, 0, 0]}>
        <boxGeometry args={[0.7, 0.08, 0.45]} />
        <meshStandardMaterial color="#1e4d8c" metalness={0.6} roughness={0.25} />
      </mesh>
      <mesh position={[0, 0.45, 0]}>
        <cylinderGeometry args={[0.02, 0.02, 0.35, 8]} />
        <meshStandardMaterial color="#3dd6a5" />
      </mesh>
    </group>
  );
}

function fitCadScene(scene, targetSize = 1.65) {
  const root = scene.clone(true);
  root.updateMatrixWorld(true);
  const box = new THREE.Box3().setFromObject(root);
  const size = new THREE.Vector3();
  box.getSize(size);
  const maxDim = Math.max(size.x, size.y, size.z) || 1;
  root.scale.multiplyScalar(targetSize / maxDim);
  root.updateMatrixWorld(true);
  box.setFromObject(root);
  const center = new THREE.Vector3();
  box.getCenter(center);
  root.position.sub(center);
  root.traverse((obj) => {
    if (obj.isMesh) {
      obj.castShadow = false;
      obj.receiveShadow = false;
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      mats.forEach((mat) => {
        if (!mat) return;
        mat.side = THREE.DoubleSide;
        if ('metalness' in mat) mat.metalness = Math.min(0.45, mat.metalness ?? 0.3);
        if ('roughness' in mat) mat.roughness = Math.max(0.35, mat.roughness ?? 0.5);
      });
    }
  });
  return root;
}

/** Team CAD (PRD A.5.9). Converter baked longest axis to +Y. */
function CadMesh({ url }) {
  const gltf = useGLTF(url);
  const scene = useMemo(() => fitCadScene(gltf.scene), [gltf.scene]);
  return <primitive object={scene} />;
}

class CadFallbackBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { failed: false };
  }

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(err) {
    console.warn('[Body3D] CAD GLB failed, using procedural mesh', err);
  }

  render() {
    if (this.state.failed) return this.props.fallback;
    return this.props.children;
  }
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
  const pitch = useStore((s) => s.telemetry.pitch) ?? 0;
  const yaw = useStore((s) => s.telemetry.yaw) ?? 0;
  const roll = useStore((s) => s.telemetry.roll) ?? 0;

  target.current = { pitch, yaw: wrap360(yaw), roll };

  useFrame((_, dt) => {
    if (!group.current) return;
    const k = 1 - Math.exp(-8 * Math.min(dt, 0.05));
    const s = smooth.current;
    const t = target.current;

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

  const procedural =
    vehicleKind === 'satellite' ? <SatelliteMesh /> : <RocketMesh />;
  const url = CAD_URL[vehicleKind] || CAD_URL.rocket;

  return (
    <group ref={group}>
      <CadFallbackBoundary fallback={procedural}>
        <Suspense fallback={null}>
          <CadMesh url={url} />
        </Suspense>
      </CadFallbackBoundary>
    </group>
  );
}

function Fallback() {
  return <div className="body3d-fallback">3D view unavailable</div>;
}

/**
 * 3D tilt/body animation via react-three-fiber (PRD G6 / A.5.9).
 * Real STEP→GLB CAD with procedural fallback.
 */
export default function Body3D({ vehicle }) {
  const vehicleKind = vehicle === 'satellite' ? 'satellite' : 'rocket';
  const accent = vehicleKind === 'satellite' ? '#3dd6a5' : '#f0733d';
  const cadLabel = vehicleKind === 'satellite' ? 'CanSat CAD' : 'Rocket CAD';

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
            <OrbitControls
              enablePan={false}
              enableDamping
              minDistance={1.2}
              maxDistance={6}
            />
          </Canvas>
        </Suspense>
      </div>
      <div className="body3d-caption muted small">
        {cadLabel} · live pitch/yaw/roll · drag to orbit
      </div>
    </div>
  );
}

useGLTF.preload(CAD_URL.rocket);
useGLTF.preload(CAD_URL.satellite);
