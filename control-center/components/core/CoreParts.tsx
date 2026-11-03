"use client";

/**
 * Additional procedural structures for the AI core. All share the scene uniforms
 * (uTime, uIntensity, uContract = "thinking", uSwirl = "executing", uDim, uWarn, uColor, uWarm, uPixel),
 * so every layer reacts to the same business state.
 *
 *  Seed      – bright pulsing kernel at the centre
 *  Lattice   – counter-rotating geodesic frames inside the nucleus (two scales)
 *  Cage      – faint outer geodesic cage with glowing vertices; "breathes" with activity
 *  Synapses  – arcs over the nucleus that fire travelling pulses (rate rises while thinking)
 *  Disk      – tilted accretion disk with Keplerian rotation (speeds up while executing)
 *  Meridians – thin latitude/longitude scan lines sweeping the shell
 */
import { useFrame } from "@react-three/fiber";
import { useEffect, useMemo, useRef } from "react";
import * as THREE from "three";


// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type SharedUniforms = Record<string, { value: any }>;

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

const COLOR_FN = /* glsl */ `
  uniform vec3 uColor; uniform vec3 uWarm; uniform float uWarn; uniform float uDim;
  vec3 tone(vec3 c){ vec3 b = mix(c, uWarm, uWarn*0.7); return mix(b, vec3(0.45,0.52,0.6), uDim); }
`;

function useDispose(...items: { dispose: () => void }[]) {
  useEffect(() => () => items.forEach((i) => i.dispose()), items); // eslint-disable-line react-hooks/exhaustive-deps
}

export function Seed({ u }: { u: SharedUniforms }) {
  const ref = useRef<THREE.Mesh>(null);
  const geo = useMemo(() => new THREE.IcosahedronGeometry(0.16, 3), []);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `varying vec3 vN; varying vec3 vV; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vN = normalize(normalMatrix*normal); vV = normalize(-mv.xyz); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `${COLOR_FN} uniform float uIntensity; varying vec3 vN; varying vec3 vV;
      void main(){ float f = pow(max(dot(vN,vV),0.0), 1.5); vec3 c = mix(tone(uColor), vec3(1.0), 0.75) * (0.6 + uIntensity);
      gl_FragColor = vec4(c, f*(0.55+uIntensity*0.45)*(1.0-uDim*0.6)); }`,
  }), [u]);
  useDispose(geo, mat);
  useFrame(() => {
    const t = u.uTime.value as number;
    const k = 1 + Math.sin(t * (1.6 + (u.uContract.value as number) * 4)) * 0.12 + (u.uContract.value as number) * 0.25;
    ref.current?.scale.setScalar(k);
  });
  return <mesh ref={ref} geometry={geo} material={mat} />;
}

function wire(radius: number, detail: number) {
  const g = new THREE.WireframeGeometry(new THREE.IcosahedronGeometry(radius, detail));
  return g;
}

export function Lattice({ u }: { u: SharedUniforms }) {
  const a = useRef<THREE.LineSegments>(null);
  const b = useRef<THREE.LineSegments>(null);
  const geoA = useMemo(() => wire(0.58, 1), []);
  const geoB = useMemo(() => wire(0.36, 0), []);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `varying float vZ; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vZ = mv.z; gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `${COLOR_FN} uniform float uIntensity; uniform float uContract; varying float vZ;
      void main(){ float depth = smoothstep(-7.5, -5.4, vZ); gl_FragColor = vec4(tone(uColor), (0.10 + uIntensity*0.22 + uContract*0.25) * depth * (1.0-uDim*0.7)); }`,
  }), [u]);
  useDispose(geoA, geoB, mat);
  useFrame((_, dt) => {
    const s = Math.min(dt, 0.05) * (0.15 + (u.uContract.value as number) * 0.9 + (u.uSwirl.value as number) * 0.4);
    if (a.current) { a.current.rotation.y += s; a.current.rotation.x += s * 0.4; }
    if (b.current) { b.current.rotation.y -= s * 1.6; b.current.rotation.z += s * 0.7; }
  });
  return (
    <group>
      <lineSegments ref={a} geometry={geoA} material={mat} />
      <lineSegments ref={b} geometry={geoB} material={mat} />
    </group>
  );
}

export function Cage({ u }: { u: SharedUniforms }) {
  const ref = useRef<THREE.Group>(null);
  const lines = useMemo(() => new THREE.EdgesGeometry(new THREE.IcosahedronGeometry(1.18, 1)), []);
  const verts = useMemo(() => {
    const src = new THREE.IcosahedronGeometry(1.18, 1);
    const pos = src.getAttribute("position");
    const seen = new Map<string, THREE.Vector3>();
    for (let i = 0; i < pos.count; i++) {
      const v = new THREE.Vector3().fromBufferAttribute(pos, i);
      seen.set(`${v.x.toFixed(3)},${v.y.toFixed(3)},${v.z.toFixed(3)}`, v);
    }
    src.dispose();
    const g = new THREE.BufferGeometry().setFromPoints([...seen.values()]);
    const seeds = new Float32Array(seen.size).map((_, i) => (i * 0.6180339) % 1);
    g.setAttribute("aSeed", new THREE.BufferAttribute(seeds, 1));
    return g;
  }, []);
  const lineMat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `varying float vZ; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vZ = mv.z; gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `${COLOR_FN} uniform float uIntensity; uniform float uSwirl; varying float vZ;
      void main(){ float depth = smoothstep(-7.6, -5.0, vZ); gl_FragColor = vec4(tone(uColor), (0.035 + uIntensity*0.05 + uSwirl*0.05) * depth); }`,
  }), [u]);
  const ptMat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `uniform float uTime; uniform float uPixel; attribute float aSeed; varying float vA;
      void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vA = 0.35 + 0.65*pow(0.5+0.5*sin(uTime*1.7 + aSeed*31.0), 4.0);
      gl_PointSize = uPixel * (2.0 + vA*3.0) * (6.0 / -mv.z); gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `${COLOR_FN} uniform float uIntensity; varying float vA;
      void main(){ float d = length(gl_PointCoord-0.5); if (d>0.5) discard; gl_FragColor = vec4(mix(tone(uColor), vec3(1.0), 0.4), smoothstep(0.5,0.0,d)*vA*(0.2+uIntensity*0.5)*(1.0-uDim*0.6)); }`,
  }), [u]);
  useDispose(lines, verts, lineMat, ptMat);
  useFrame((_, dt) => {
    const g = ref.current;
    if (!g) return;
    g.rotation.y -= Math.min(dt, 0.05) * (0.03 + (u.uSwirl.value as number) * 0.12);
    const breathe = 1 + Math.sin((u.uTime.value as number) * 0.9) * 0.015 + (u.uContract.value as number) * -0.06;
    g.scale.setScalar(breathe);
  });
  return (
    <group ref={ref}>
      <lineSegments geometry={lines} material={lineMat} />
      <points geometry={verts} material={ptMat} />
    </group>
  );
}

export function Synapses({ u, count }: { u: SharedUniforms; count: number }) {
  const geo = useMemo(() => {
    const r = rng(9001 + count);
    const SEG = 40;
    const pos: number[] = [], t: number[] = [], seed: number[] = [];
    const randDir = () => {
      const z = r() * 2 - 1, a = r() * Math.PI * 2, s = Math.sqrt(1 - z * z);
      return new THREE.Vector3(Math.cos(a) * s, z, Math.sin(a) * s);
    };
    for (let i = 0; i < count; i++) {
      const a = randDir();
      let b = randDir();
      while (a.angleTo(b) < 0.5 || a.angleTo(b) > 2.0) b = randDir();
      const lift = 0.18 + r() * 0.35, base = 0.86 + r() * 0.1, sd = r();
      const pt = (k: number) => {
        const v = a.clone().lerp(b, k).normalize();
        return v.multiplyScalar(base + Math.sin(Math.PI * k) * lift);
      };
      for (let k = 0; k < SEG; k++) {
        const p0 = pt(k / SEG), p1 = pt((k + 1) / SEG);
        pos.push(p0.x, p0.y, p0.z, p1.x, p1.y, p1.z);
        t.push(k / SEG, (k + 1) / SEG);
        seed.push(sd, sd);
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
    g.setAttribute("aT", new THREE.Float32BufferAttribute(t, 1));
    g.setAttribute("aSeed", new THREE.Float32BufferAttribute(seed, 1));
    return g;
  }, [count]);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `attribute float aT; attribute float aSeed; varying float vT; varying float vS; varying float vZ;
      void main(){ vT = aT; vS = aSeed; vec4 mv = modelViewMatrix*vec4(position,1.0); vZ = mv.z; gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `${COLOR_FN} uniform float uTime; uniform float uIntensity; uniform float uContract; uniform float uSwirl;
      varying float vT; varying float vS; varying float vZ;
      void main(){
        float rate = 0.18 + uContract*0.9 + uSwirl*0.35;
        float cycle = uTime*rate + vS*13.0;
        float phase = fract(cycle);
        float fire = step(fract(vS*7.0 + floor(cycle)*0.618), 0.35 + uContract*0.55); // only some arcs fire each cycle
        float head = smoothstep(0.12, 0.0, abs(vT - phase*1.25 + 0.1));
        float depth = smoothstep(-7.4, -5.2, vZ);
        float a = (0.025 + head*fire*(0.55 + uIntensity*0.45)) * depth * (1.0 - uDim*0.8);
        gl_FragColor = vec4(mix(tone(uColor), vec3(1.0), head*0.6), a);
      }`,
  }), [u]);
  useDispose(geo, mat);
  return <lineSegments geometry={geo} material={mat} />;
}

export function Disk({ u, count }: { u: SharedUniforms; count: number }) {
  const geo = useMemo(() => {
    const r = rng(77 + count);
    const g = new THREE.BufferGeometry();
    const rad = new Float32Array(count), ang = new Float32Array(count), h = new Float32Array(count), sd = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      rad[i] = 1.55 + Math.pow(r(), 0.7) * 1.1;
      ang[i] = r() * Math.PI * 2;
      h[i] = (r() - 0.5) * 0.06 * (rad[i] - 1.2);
      sd[i] = r();
    }
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(count * 3), 3));
    g.setAttribute("aRad", new THREE.BufferAttribute(rad, 1));
    g.setAttribute("aAng", new THREE.BufferAttribute(ang, 1));
    g.setAttribute("aH", new THREE.BufferAttribute(h, 1));
    g.setAttribute("aSeed", new THREE.BufferAttribute(sd, 1));
    g.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4);
    return g;
  }, [count]);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `uniform float uTime; uniform float uSwirl; uniform float uPixel; attribute float aRad; attribute float aAng; attribute float aH; attribute float aSeed;
      varying float vA;
      void main(){
        float w = (0.06 + uSwirl*0.55) / pow(aRad, 1.5);           // Keplerian: inner ring faster
        float a = aAng + uTime * w * 2.2;
        vec3 p = vec3(cos(a)*aRad, aH, sin(a)*aRad);
        vec4 mv = modelViewMatrix*vec4(p,1.0);
        float band = 0.5 + 0.5*sin(aRad*22.0);                    // ring banding
        vA = (0.25 + 0.75*band) * (1.0 - smoothstep(2.2, 2.7, aRad)) * (0.6 + 0.4*sin(uTime*2.0 + aSeed*20.0));
        gl_PointSize = uPixel * (1.1 + aSeed*1.3) * (6.0 / -mv.z);
        gl_Position = projectionMatrix*mv;
      }`,
    fragmentShader: `${COLOR_FN} uniform float uIntensity; uniform float uSwirl; varying float vA;
      void main(){ float d = length(gl_PointCoord-0.5); if (d>0.5) discard;
        gl_FragColor = vec4(tone(mix(uColor, vec3(0.23,0.51,0.96), 0.35)), smoothstep(0.5,0.0,d)*vA*(0.18+uIntensity*0.3+uSwirl*0.25)*(1.0-uDim*0.7)); }`,
  }), [u]);
  useDispose(geo, mat);
  return (
    <group rotation={[1.18, 0.0, -0.32]}>
      <points geometry={geo} material={mat} />
    </group>
  );
}

export function Meridians({ u }: { u: SharedUniforms }) {
  const ref = useRef<THREE.Group>(null);
  const geo = useMemo(() => {
    const pts: THREE.Vector3[] = [];
    const R = 1.02;
    for (let i = 0; i < 128; i++) {
      const a = (i / 128) * Math.PI * 2, b = ((i + 1) / 128) * Math.PI * 2;
      pts.push(new THREE.Vector3(Math.cos(a) * R, 0, Math.sin(a) * R), new THREE.Vector3(Math.cos(b) * R, 0, Math.sin(b) * R));
    }
    return new THREE.BufferGeometry().setFromPoints(pts);
  }, []);
  const mat = useMemo(() => new THREE.ShaderMaterial({
    uniforms: u, transparent: true, depthWrite: false, blending: THREE.AdditiveBlending,
    vertexShader: `varying float vZ; void main(){ vec4 mv = modelViewMatrix*vec4(position,1.0); vZ = mv.z; gl_Position = projectionMatrix*mv; }`,
    fragmentShader: `${COLOR_FN} uniform float uIntensity; varying float vZ; void main(){ float depth = smoothstep(-7.2,-5.2,vZ); gl_FragColor = vec4(tone(uColor), (0.12+uIntensity*0.25)*depth*(1.0-uDim*0.7)); }`,
  }), [u]);
  useDispose(geo, mat);
  const rings = useRef<THREE.LineSegments[]>([]);
  useFrame(() => {
    const t = u.uTime.value as number;
    const speed = 0.25 + (u.uContract.value as number) * 0.6 + (u.uSwirl.value as number) * 0.3;
    rings.current.forEach((ring, i) => {
      if (!ring) return;
      const ph = (t * speed + i / 3) % 1;                  // latitude scan from pole to pole
      const y = Math.cos(ph * Math.PI) * 1.0;
      const s = Math.sqrt(Math.max(0, 1 - y * y));
      ring.position.y = y;
      ring.scale.set(s, 1, s);
    });
    if (ref.current) ref.current.rotation.z = Math.sin(t * 0.1) * 0.3;
  });
  return (
    <group ref={ref}>
      {[0, 1, 2].map((i) => <lineSegments key={i} geometry={geo} material={mat} ref={(m) => { if (m) rings.current[i] = m; }} />)}
    </group>
  );
}
