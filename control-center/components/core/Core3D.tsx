"use client";

/**
 * Original AI core: a displaced luminous nucleus, a particle shell whose motion follows the business state,
 * three tilted orbits with travelling sparks, a one-shot success ripple, and slow background dust.
 * Everything is procedural (no external assets). Uniforms are eased toward per-state targets every frame.
 */
import { Canvas, useFrame, useThree } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";
import type { CoreVisual } from "@/lib/coreState";
import { Cage, Disk, Lattice, Meridians, Seed, Synapses } from "./CoreParts";

/* eslint-disable react-hooks/immutability -- three.js objects (uniforms, materials, meshes) are mutated imperatively
   inside useFrame by design; React never renders from these values. */

/** Small deterministic PRNG so geometry generation stays pure (same layout on every mount). */
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

export type Quality = "low" | "mid" | "high";

type Targets = { contract: number; swirl: number; intensity: number; dim: number; warn: number; orbit: number };
const TARGETS: Record<CoreVisual, Targets> = {
  idle: { contract: 0, swirl: 0.12, intensity: 0.62, dim: 0, warn: 0, orbit: 0.25 },
  thinking: { contract: 1, swirl: 0.3, intensity: 1, dim: 0, warn: 0, orbit: 0.35 },
  executing: { contract: 0.15, swirl: 1, intensity: 0.9, dim: 0, warn: 0, orbit: 1 },
  error: { contract: 0.05, swirl: 0.06, intensity: 0.5, dim: 0.1, warn: 1, orbit: 0.1 },
  disconnected: { contract: 0, swirl: 0.02, intensity: 0.22, dim: 0.8, warn: 0, orbit: 0.03 },
};

const ACCENT = new THREE.Color("#00D9FF");
const SUPPORT = new THREE.Color("#3B82F6");
const WARN = new THREE.Color("#F59E0B");

const NOISE = /* glsl */ `
  float hash(vec3 p){ p = fract(p*0.3183099+.1); p*=17.0; return fract(p.x*p.y*p.z*(p.x+p.y+p.z)); }
  float noise(vec3 x){ vec3 i=floor(x); vec3 f=fract(x); f=f*f*(3.0-2.0*f);
    return mix(mix(mix(hash(i+vec3(0,0,0)),hash(i+vec3(1,0,0)),f.x),mix(hash(i+vec3(0,1,0)),hash(i+vec3(1,1,0)),f.x),f.y),
               mix(mix(hash(i+vec3(0,0,1)),hash(i+vec3(1,0,1)),f.x),mix(hash(i+vec3(0,1,1)),hash(i+vec3(1,1,1)),f.x),f.y),f.z); }
`;

function Nucleus({ u }: { u: Uniforms }) {
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u.nucleus,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      ${NOISE}
      uniform float uTime; uniform float uIntensity; uniform float uContract;
      varying vec3 vN; varying vec3 vView; varying float vDisp;
      void main(){
        vec3 p = position;
        float n = noise(p*2.2 + vec3(uTime*0.35)) * 0.5 + noise(p*4.5 - vec3(uTime*0.5)) * 0.25;
        float breathe = 1.0 + sin(uTime*1.1)*0.025;
        float d = n * (0.16 + uIntensity*0.12 + uContract*0.08);
        p *= breathe * (1.0 + d);
        vDisp = d;
        vec4 mv = modelViewMatrix * vec4(p,1.0);
        vN = normalize(normalMatrix * normal);
        vView = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform vec3 uWarm; uniform float uIntensity; uniform float uDim; uniform float uWarn;
      varying vec3 vN; varying vec3 vView; varying float vDisp;
      void main(){
        float fres = pow(1.0 - max(dot(vN, vView), 0.0), 2.4);
        vec3 base = mix(uColor, uWarm, uWarn*0.75);
        vec3 core = mix(base, vec3(0.92,0.98,1.0), 0.35 + vDisp*1.2);
        float facing = max(dot(vN, vView), 0.0);
        float inner = pow(facing, 6.0);                       // bright centre, glassy body
        float bands = 0.5 + 0.5*sin(vDisp*60.0);              // fine contour lines from the displacement
        vec3 col = base * fres * (0.8 + uIntensity) + vec3(0.85,0.97,1.0) * inner * (0.25 + uIntensity*0.6)
                 + core * bands * 0.05 * uIntensity;
        col = mix(col, vec3(dot(col, vec3(0.3,0.5,0.2)))*0.6, uDim);
        float a = clamp(0.04 + fres*0.8 + inner*0.22, 0.0, 1.0) * (1.0 - uDim*0.5);
        gl_FragColor = vec4(col, a);
      }`,
  }), [u]);
  const geo = useMemo(() => new THREE.IcosahedronGeometry(0.9, 24), []);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);
  return <mesh geometry={geo} material={mat} />;
}

function Shell({ u, count }: { u: Uniforms; count: number }) {
  const geo = useMemo(() => {
    const random = rng(1337 + count);
    const g = new THREE.BufferGeometry();
    const dir = new Float32Array(count * 3);
    const rad = new Float32Array(count);
    const seed = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      // fibonacci sphere + jitter → even, organic coverage
      const t = (i + 0.5) / count;
      const phi = Math.acos(1 - 2 * t);
      const th = Math.PI * (1 + Math.sqrt(5)) * i;
      const j = 0.18;
      const x = Math.sin(phi) * Math.cos(th) + (random() - 0.5) * j;
      const y = Math.cos(phi) * 0.82 + (random() - 0.5) * j;
      const z = Math.sin(phi) * Math.sin(th) + (random() - 0.5) * j;
      const l = Math.hypot(x, y, z);
      dir.set([x / l, y / l, z / l], i * 3);
      rad[i] = 1.25 + Math.pow(random(), 1.8) * 1.6;
      seed[i] = random();
    }
    g.setAttribute("position", new THREE.BufferAttribute(dir, 3));
    g.setAttribute("aRadius", new THREE.BufferAttribute(rad, 1));
    g.setAttribute("aSeed", new THREE.BufferAttribute(seed, 1));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 5);
    return g;
  }, [count]);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u.shell,
    transparent: true,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
    vertexShader: /* glsl */ `
      uniform float uTime; uniform float uContract; uniform float uSwirl; uniform float uRipple; uniform float uPixel;
      attribute float aRadius; attribute float aSeed;
      varying float vAlpha; varying float vHeat;
      mat3 rotY(float a){ float c=cos(a), s=sin(a); return mat3(c,0.,-s, 0.,1.,0., s,0.,c); }
      void main(){
        float speed = 0.04 + uSwirl * (0.35 + aSeed*0.5);
        vec3 d = rotY(uTime * speed + aSeed*6.2831) * position;
        // thinking: particles stream inward in staggered loops
        float inflow = fract(aSeed*7.0 + uTime*(0.12 + aSeed*0.1));
        float r = aRadius * mix(1.0, mix(1.0, 0.42, inflow), uContract);
        // executing: a gentle vertical wave travels around the shell
        d.y += sin(uTime*2.0 + aSeed*12.0 + d.x*3.0) * 0.06 * uSwirl;
        // success ripple: a shell-wide outward push that decays quickly
        float rip = uRipple > 0.0 ? exp(-uRipple*3.2) * sin(clamp(uRipple*6.0,0.0,3.1415)) : 0.0;
        r += rip * 0.6;
        vec4 mv = modelViewMatrix * vec4(d * r, 1.0);
        gl_Position = projectionMatrix * mv;
        float twinkle = 0.55 + 0.45*sin(uTime*(1.0+aSeed*2.0) + aSeed*40.0);
        vAlpha = twinkle * (0.35 + 0.65*(1.0 - (aRadius-1.25)/1.6));
        vHeat = clamp(uContract*inflow + rip, 0.0, 1.0);
        gl_PointSize = uPixel * (1.6 + aSeed*1.8 + vHeat*1.5) * (6.0 / -mv.z);
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 uColor; uniform vec3 uWarm; uniform float uIntensity; uniform float uDim; uniform float uWarn;
      varying float vAlpha; varying float vHeat;
      void main(){
        vec2 c = gl_PointCoord - 0.5; float d = length(c);
        if (d > 0.5) discard;
        float soft = smoothstep(0.5, 0.0, d);
        vec3 base = mix(uColor, uWarm, uWarn*0.7);
        vec3 col = mix(base, vec3(0.9,0.97,1.0), vHeat*0.7);
        col = mix(col, vec3(0.45,0.52,0.6), uDim);
        gl_FragColor = vec4(col, soft * vAlpha * (0.25 + uIntensity*0.75) * (1.0 - uDim*0.6));
      }`,
  }), [u]);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);
  return <points geometry={geo} material={mat} />;
}

function Orbits({ u, live }: { u: Uniforms; live: React.RefObject<Targets> }) {
  const defs = useMemo(() => [
    { r: 1.9, tilt: [1.15, 0.2, 0], phase: 0 },
    { r: 2.3, tilt: [0.35, 0.9, 0.3], phase: 2.1 },
    { r: 2.7, tilt: [-0.6, -0.4, 0.9], phase: 4.2 },
  ], []);
  const lines = useMemo(() => defs.map((d) => {
    const pts: THREE.Vector3[] = [];
    for (let i = 0; i < 256; i++) {
      const a = (i / 256) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * d.r, Math.sin(a) * d.r * 0.92, 0));
    }
    const g = new THREE.BufferGeometry().setFromPoints(pts);
    const m = new THREE.LineBasicMaterial({ color: SUPPORT, transparent: true, opacity: 0.18, depthWrite: false,
      blending: THREE.AdditiveBlending });
    const line = new THREE.LineLoop(g, m);
    line.rotation.set(d.tilt[0], d.tilt[1], d.tilt[2]);
    return line;
  }), [defs]);
  const sparkGeo = useMemo(() => new THREE.SphereGeometry(0.035, 12, 12), []);
  const sparkMat = useMemo(() => new THREE.MeshBasicMaterial({ color: ACCENT, transparent: true, opacity: 0.9,
    blending: THREE.AdditiveBlending, depthWrite: false }), []);
  const sparks = useRef<THREE.Mesh[]>([]);
  const angle = useRef(defs.map((d) => d.phase));
  useEffect(() => () => {
    lines.forEach((l) => { l.geometry.dispose(); (l.material as THREE.Material).dispose(); });
    sparkGeo.dispose();
    sparkMat.dispose();
  }, [lines, sparkGeo, sparkMat]);
  useFrame((_, dt) => {
    const step = Math.min(dt, 0.05);
    defs.forEach((d, i) => {
      angle.current[i] += step * (0.12 + live.current.orbit * 1.1) * (i % 2 ? -1 : 1);
      const s = sparks.current[i];
      if (!s) return;
      const a = angle.current[i];
      const v = new THREE.Vector3(Math.cos(a) * d.r, Math.sin(a) * d.r * 0.92, 0);
      v.applyEuler(lines[i].rotation);
      s.position.copy(v);
      s.scale.setScalar(0.6 + live.current.orbit * 0.9);
      (lines[i].material as THREE.LineBasicMaterial).opacity = 0.08 + live.current.orbit * 0.22 * (1 - u.nucleus.uDim.value);
    });
    sparkMat.color.copy(ACCENT).lerp(WARN, u.nucleus.uWarn.value * 0.7);
    sparkMat.opacity = 0.25 + live.current.orbit * 0.7 * (1 - u.nucleus.uDim.value);
  });
  return (
    <group>
      {lines.map((l, i) => <primitive key={i} object={l} />)}
      {defs.map((_, i) => (
        <mesh key={i} geometry={sparkGeo} material={sparkMat} ref={(m) => { if (m) sparks.current[i] = m; }} />
      ))}
    </group>
  );
}

function Ripple({ u }: { u: Uniforms }) {
  const ref = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.RingGeometry(0.98, 1.0, 128), []);
  const mat = useMemo(() => new THREE.MeshBasicMaterial({ color: ACCENT, transparent: true, opacity: 0, side: THREE.DoubleSide,
    blending: THREE.AdditiveBlending, depthWrite: false }), []);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);
  useFrame(() => {
    const t = u.shell.uRipple.value;
    const m = ref.current;
    if (!m) return;
    if (t <= 0 || t > 1.6) { mat.opacity = 0; return; }
    const k = t / 1.6;
    m.scale.setScalar(1.1 + k * 2.6);
    mat.opacity = (1 - k) * 0.55;
  });
  return <mesh ref={ref} geometry={geo} material={mat} />;
}

function Dust({ count }: { count: number }) {
  const geo = useMemo(() => {
    const random = rng(42 + count);
    const g = new THREE.BufferGeometry();
    const p = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      const r = 5 + random() * 7;
      const a = random() * Math.PI * 2;
      const y = (random() - 0.5) * 8;
      p.set([Math.cos(a) * r, y, Math.sin(a) * r - 4], i * 3);
    }
    g.setAttribute("position", new THREE.BufferAttribute(p, 3));
    return g;
  }, [count]);
  const mat = useMemo(() => new THREE.PointsMaterial({ color: "#3B82F6", size: 0.025, transparent: true, opacity: 0.35,
    depthWrite: false, blending: THREE.AdditiveBlending }), []);
  const ref = useRef<THREE.Points>(null);
  useEffect(() => () => { geo.dispose(); mat.dispose(); }, [geo, mat]);
  useFrame((_, dt) => { if (ref.current) ref.current.rotation.y += Math.min(dt, 0.05) * 0.01; });
  return <points ref={ref} geometry={geo} material={mat} />;
}

type Uniforms = {
  nucleus: Record<"uTime" | "uIntensity" | "uContract" | "uDim" | "uWarn", { value: number }> & Record<"uColor" | "uWarm", { value: THREE.Color }>;
  shell: Record<"uTime" | "uIntensity" | "uContract" | "uSwirl" | "uRipple" | "uDim" | "uWarn" | "uPixel", { value: number }> & Record<"uColor" | "uWarm", { value: THREE.Color }>;
};

function Scene({ visual, pulseKey, quality, reducedMotion }: Props) {
  const { invalidate, gl } = useThree();
  const u = useMemo<Uniforms>(() => ({
    nucleus: { uTime: { value: 0 }, uIntensity: { value: 0.5 }, uContract: { value: 0 }, uDim: { value: 0.5 }, uWarn: { value: 0 },
      uColor: { value: ACCENT.clone() }, uWarm: { value: WARN.clone() } },
    shell: { uTime: { value: 0 }, uIntensity: { value: 0.5 }, uContract: { value: 0 }, uSwirl: { value: 0 }, uRipple: { value: 0 },
      uDim: { value: 0.5 }, uWarn: { value: 0 }, uPixel: { value: 1 }, uColor: { value: ACCENT.clone() }, uWarm: { value: WARN.clone() } },
  }), []);
  const live = useRef({ ...TARGETS.idle });
  const group = useRef<THREE.Group>(null);
  const pointer = useRef({ x: 0, y: 0 });
  const rippleStart = useRef<number | null>(null);
  const clock = useRef(0);

  useEffect(() => {
    u.shell.uPixel.value = Math.min(gl.getPixelRatio(), 2);
  }, [gl, u]);

  useEffect(() => {
    const onMove = (e: PointerEvent) => {
      pointer.current.x = (e.clientX / window.innerWidth - 0.5) * 2;
      pointer.current.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    if (!reducedMotion) window.addEventListener("pointermove", onMove, { passive: true });
    return () => window.removeEventListener("pointermove", onMove);
  }, [reducedMotion]);

  useEffect(() => {
    if (!pulseKey) return;
    if (reducedMotion) {
      // no motion: snap to a brief brighter frame instead of an animated ripple
      live.current.intensity = 1;
      invalidate();
      return;
    }
    rippleStart.current = clock.current;
  }, [pulseKey, reducedMotion, invalidate]);

  useEffect(() => {
    if (reducedMotion) {
      Object.assign(live.current, TARGETS[visual]);
      invalidate();
    }
  }, [visual, reducedMotion, invalidate]);

  useFrame((_, delta) => {
    const dt = reducedMotion ? 0 : Math.min(delta, 0.05);
    clock.current += dt;
    const t = TARGETS[visual];
    const k = reducedMotion ? 1 : 1 - Math.exp(-dt * 2.2);
    const L = live.current;
    (Object.keys(t) as (keyof Targets)[]).forEach((key) => { L[key] += (t[key] - L[key]) * k; });
    const ripple = rippleStart.current === null ? 0 : clock.current - rippleStart.current;
    if (ripple > 2) rippleStart.current = null;
    for (const set of [u.nucleus, u.shell]) {
      set.uTime.value = clock.current;
      set.uIntensity.value = L.intensity;
      set.uContract.value = L.contract;
      set.uDim.value = L.dim;
      set.uWarn.value = L.warn;
    }
    u.shell.uSwirl.value = L.swirl;
    u.shell.uRipple.value = rippleStart.current === null ? 0 : Math.max(ripple, 0.0001);
    if (group.current) {
      group.current.rotation.y += (pointer.current.x * 0.25 - group.current.rotation.y) * 0.04 + dt * 0.03;
      group.current.rotation.x += (pointer.current.y * 0.15 - group.current.rotation.x) * 0.04;
    }
  });

  const shellCount = quality === "high" ? 5200 : quality === "mid" ? 2800 : 1200;
  return (
    <group ref={group}>
      <Dust count={quality === "low" ? 150 : 400} />
      <Disk u={u.shell} count={quality === "high" ? 2600 : quality === "mid" ? 1500 : 600} />
      <Orbits u={u} live={live} />
      <Cage u={u.shell} />
      <Shell u={u} count={shellCount} />
      <Synapses u={u.shell} count={quality === "low" ? 14 : 30} />
      <Nucleus u={u} />
      <Lattice u={u.shell} />
      <Meridians u={u.shell} />
      <Seed u={u.shell} />
      <Ripple u={u} />
    </group>
  );
}

type Props = { visual: CoreVisual; pulseKey: string | null; quality: Quality; reducedMotion: boolean };

export default function Core3D(props: Props & { paused: boolean; onContextLost: () => void }) {
  const { paused, onContextLost, ...rest } = props;
  const dprMax = props.quality === "high" ? 1.75 : props.quality === "mid" ? 1.5 : 1.1;
  return (
    <Canvas
      className="!absolute inset-0"
      dpr={[1, dprMax]}
      frameloop={paused ? "never" : props.reducedMotion ? "demand" : "always"}
      camera={{ position: [0, 0, 6.2], fov: 45 }}
      gl={{ antialias: props.quality !== "low", alpha: true, powerPreference: "high-performance" }}
      onCreated={({ gl }) => {
        gl.setClearColor(0x000000, 0);
        gl.domElement.addEventListener("webglcontextlost", (e) => { e.preventDefault(); onContextLost(); }, { once: true });
      }}
      style={{ touchAction: "pan-y" }}
      aria-hidden
    >
      <Scene {...rest} />
    </Canvas>
  );
}
