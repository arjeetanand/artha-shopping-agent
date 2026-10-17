import { useEffect, useRef } from 'react';
import * as THREE from 'three';

/**
 * ThreeBackground — Animated Ambient 3D Spatial Field
 *
 * Renders a fixed, full-viewport 3D canvas behind all UI at z-index: 0:
 * - Floating particle constellation with subtle neural connectivity lines
 * - Smooth mouse-reactive camera parallax
 * - Responds to live agent research status (subtle acceleration & aura pulse when searching)
 * - Low-power WebGL configuration (devicePixelRatio capped, no heavy post-processing)
 * - Respects prefers-reduced-motion: static snapshot render only
 * - Complete resource disposal on unmount
 */
export function ThreeBackground({ isSearching = false, hasResults = false }) {
  const canvasRef = useRef(null);
  const stateRef = useRef({ isSearching, hasResults });
  stateRef.current = { isSearching, hasResults };

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // ── Renderer ──────────────────────────────────────────────────────────────
    const renderer = new THREE.WebGLRenderer({
      canvas,
      alpha: true,
      antialias: false,
      powerPreference: 'low-power',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.5));
    renderer.setSize(window.innerWidth, window.innerHeight);
    renderer.setClearColor(0x000000, 0);

    // ── Scene & Camera ────────────────────────────────────────────────────────
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(60, window.innerWidth / window.innerHeight, 0.1, 1000);
    camera.position.z = 85;

    // ── Particle Geometry ─────────────────────────────────────────────────────
    const PARTICLE_COUNT = window.innerWidth < 768 ? 220 : 440;
    const positions = new Float32Array(PARTICLE_COUNT * 3);
    const colors = new Float32Array(PARTICLE_COUNT * 3);
    const sizes = new Float32Array(PARTICLE_COUNT);

    // Palette: Coral (#EE5A3B), Cobalt (#2D5BD1), Violet (#7C3AED), Emerald (#287E5D)
    const palette = [
      new THREE.Color(0xee5a3b),
      new THREE.Color(0x2d5bd1),
      new THREE.Color(0x7c3aed),
      new THREE.Color(0x287e5d),
    ];

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const i3 = i * 3;
      positions[i3]     = (Math.random() - 0.5) * 220;
      positions[i3 + 1] = (Math.random() - 0.5) * 190;
      positions[i3 + 2] = (Math.random() - 0.5) * 110;

      const color = palette[Math.floor(Math.random() * palette.length)];
      colors[i3]     = color.r;
      colors[i3 + 1] = color.g;
      colors[i3 + 2] = color.b;

      sizes[i] = Math.random() * 1.6 + 0.4;
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3));
    particleGeo.setAttribute('size', new THREE.BufferAttribute(sizes, 1));

    const particleMat = new THREE.PointsMaterial({
      size: 1.2,
      vertexColors: true,
      transparent: true,
      opacity: 0.28,
      blending: THREE.NormalBlending,
      depthWrite: false,
      sizeAttenuation: true,
    });

    const particles = new THREE.Points(particleGeo, particleMat);
    scene.add(particles);

    // ── Connection Lines ──────────────────────────────────────────────────────
    const LINE_THRESHOLD = 26;
    const linePositions = [];
    const lineColors = [];

    const pos = particleGeo.attributes.position.array;
    const col = particleGeo.attributes.color.array;

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const ax = pos[i * 3], ay = pos[i * 3 + 1], az = pos[i * 3 + 2];
      for (let j = i + 1; j < PARTICLE_COUNT; j++) {
        const dx = ax - pos[j * 3];
        const dy = ay - pos[j * 3 + 1];
        const dz = az - pos[j * 3 + 2];
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz);
        if (dist < LINE_THRESHOLD) {
          linePositions.push(ax, ay, az, pos[j * 3], pos[j * 3 + 1], pos[j * 3 + 2]);
          const alpha = 1 - dist / LINE_THRESHOLD;
          lineColors.push(
            col[i * 3] * alpha, col[i * 3 + 1] * alpha, col[i * 3 + 2] * alpha,
            col[j * 3] * alpha, col[j * 3 + 1] * alpha, col[j * 3 + 2] * alpha,
          );
        }
      }
    }

    const lineGeo = new THREE.BufferGeometry();
    lineGeo.setAttribute('position', new THREE.Float32BufferAttribute(linePositions, 3));
    lineGeo.setAttribute('color', new THREE.Float32BufferAttribute(lineColors, 3));

    const lineMat = new THREE.LineBasicMaterial({
      vertexColors: true,
      transparent: true,
      opacity: 0.12,
      blending: THREE.NormalBlending,
      depthWrite: false,
    });

    const lines = new THREE.LineSegments(lineGeo, lineMat);
    scene.add(lines);

    // ── Mouse Parallax ────────────────────────────────────────────────────────
    const mouse = { x: 0, y: 0 };
    const targetCam = { x: 0, y: 0 };

    const onMouseMove = (e) => {
      mouse.x = (e.clientX / window.innerWidth - 0.5) * 2;
      mouse.y = (e.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener('mousemove', onMouseMove, { passive: true });

    // ── Animation Loop ────────────────────────────────────────────────────────
    let rafId;
    let time = 0;

    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const { isSearching: searching } = stateRef.current;
      time += searching ? 0.0028 : 0.0009;

      if (!prefersReducedMotion) {
        particles.rotation.y = time * 0.08;
        particles.rotation.x = Math.sin(time * 0.05) * 0.07;
        lines.rotation.y = particles.rotation.y;
        lines.rotation.x = particles.rotation.x;

        // Camera parallax towards mouse
        targetCam.x += (mouse.x * 5 - targetCam.x) * 0.025;
        targetCam.y += (-mouse.y * 4 - targetCam.y) * 0.025;
        camera.position.x = targetCam.x;
        camera.position.y = targetCam.y;
        camera.lookAt(scene.position);

        // Opacity breathing
        particleMat.opacity = searching ? 0.42 + Math.sin(time * 4) * 0.08 : 0.24 + Math.sin(time * 1.5) * 0.05;
        lineMat.opacity = searching ? 0.22 : 0.12;
      }

      renderer.render(scene, camera);
    };

    animate();

    // ── Resize ────────────────────────────────────────────────────────────────
    const onResize = () => {
      camera.aspect = window.innerWidth / window.innerHeight;
      camera.updateProjectionMatrix();
      renderer.setSize(window.innerWidth, window.innerHeight);
    };
    window.addEventListener('resize', onResize);

    // ── Cleanup ───────────────────────────────────────────────────────────────
    return () => {
      cancelAnimationFrame(rafId);
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('resize', onResize);
      particleGeo.dispose();
      particleMat.dispose();
      lineGeo.dispose();
      lineMat.dispose();
      renderer.dispose();
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      className="three-bg-canvas"
      aria-hidden="true"
      style={{
        position: 'fixed',
        inset: 0,
        zIndex: 0,
        pointerEvents: 'none',
        width: '100%',
        height: '100%',
      }}
    />
  );
}
