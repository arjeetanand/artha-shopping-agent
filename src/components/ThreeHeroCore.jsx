import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

/**
 * ThreeHeroCore — Interactive 3D Autonomous AI Agent Core
 *
 * Renders an interactive 3D holographic quantum core in the hero section:
 * - 3D Icosahedron wireframe lattice with metallic luster
 * - Inner luminous core sphere
 * - 3 Orbital energy rings with 7 floating specialist agent nodes
 * - Surrounding particle constellation
 * - Interactive: Pointer drag & hover freely rotates the core in 3D
 * - State-reactive: Spins faster during search, pulses emerald on complete, amber on clarification
 * - Fully accessible & respects prefers-reduced-motion
 */
export function ThreeHeroCore({ isSearching = false, status = 'idle', onExplore }) {
  const containerRef = useRef(null);
  const stateRef = useRef({ isSearching, status });
  stateRef.current = { isSearching, status };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    // Dimensions
    const width = container.clientWidth || 340;
    const height = container.clientHeight || 360;

    // Renderer
    const renderer = new THREE.WebGLRenderer({
      alpha: true,
      antialias: true,
      powerPreference: 'high-performance',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(width, height);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);

    // Scene & Camera
    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, width / height, 0.1, 1000);
    camera.position.z = 52;

    // Lighting
    const ambientLight = new THREE.AmbientLight(0xffffff, 0.9);
    scene.add(ambientLight);

    const coralLight = new THREE.PointLight(0xee5a3b, 3, 100);
    coralLight.position.set(30, 25, 25);
    scene.add(coralLight);

    const cobaltLight = new THREE.PointLight(0x2d5bd1, 3, 100);
    cobaltLight.position.set(-30, -25, 25);
    scene.add(cobaltLight);

    const emeraldLight = new THREE.PointLight(0x287e5d, 0, 80);
    emeraldLight.position.set(0, 0, 30);
    scene.add(emeraldLight);

    // Master Group
    const masterGroup = new THREE.Group();
    scene.add(masterGroup);

    // 1. Outer Icosahedron Lattice
    const icoGeo = new THREE.IcosahedronGeometry(13.5, 1);
    const icoMat = new THREE.MeshStandardMaterial({
      color: 0xee5a3b,
      wireframe: true,
      roughness: 0.15,
      metalness: 0.85,
      transparent: true,
      opacity: 0.65,
    });
    const icosahedron = new THREE.Mesh(icoGeo, icoMat);
    masterGroup.add(icosahedron);

    // 2. Middle Dodecahedron Cage
    const dodecGeo = new THREE.DodecahedronGeometry(10.5, 0);
    const dodecMat = new THREE.MeshStandardMaterial({
      color: 0x2d5bd1,
      wireframe: true,
      roughness: 0.2,
      metalness: 0.7,
      transparent: true,
      opacity: 0.5,
    });
    const dodecahedron = new THREE.Mesh(dodecGeo, dodecMat);
    masterGroup.add(dodecahedron);

    // 3. Inner Quantum Core Sphere
    const coreGeo = new THREE.SphereGeometry(6, 32, 32);
    const coreMat = new THREE.MeshStandardMaterial({
      color: 0x141414,
      emissive: 0x2d5bd1,
      emissiveIntensity: 0.6,
      roughness: 0.3,
      metalness: 0.9,
    });
    const coreSphere = new THREE.Mesh(coreGeo, coreMat);
    masterGroup.add(coreSphere);

    // 4. Three Orbital Rings (Tilted)
    const ringGroup = new THREE.Group();
    masterGroup.add(ringGroup);

    const createRing = (radius, tube, rotX, rotY, color) => {
      const geo = new THREE.TorusGeometry(radius, tube, 16, 64);
      const mat = new THREE.MeshBasicMaterial({
        color,
        transparent: true,
        opacity: 0.38,
      });
      const ring = new THREE.Mesh(geo, mat);
      ring.rotation.x = rotX;
      ring.rotation.y = rotY;
      ringGroup.add(ring);
      return ring;
    };

    const ring1 = createRing(18, 0.18, Math.PI / 3, 0, 0xee5a3b);
    const ring2 = createRing(21, 0.16, -Math.PI / 4, Math.PI / 6, 0x2d5bd1);
    const ring3 = createRing(24, 0.14, Math.PI / 6, -Math.PI / 3, 0x287e5d);

    // 5. 7 Autonomous Specialist Agent Satellites
    const agentNodes = [];
    const agentColors = [0xee5a3b, 0x2d5bd1, 0x287e5d, 0x7c3aed, 0x0694d6, 0xf59e0b, 0xec4899];
    const AGENT_COUNT = 7;
    const nodeGeo = new THREE.SphereGeometry(0.85, 16, 16);

    for (let i = 0; i < AGENT_COUNT; i++) {
      const mat = new THREE.MeshStandardMaterial({
        color: agentColors[i % agentColors.length],
        emissive: agentColors[i % agentColors.length],
        emissiveIntensity: 0.8,
        roughness: 0.1,
      });
      const node = new THREE.Mesh(nodeGeo, mat);
      ringGroup.add(node);
      agentNodes.push({
        mesh: node,
        radius: 17 + (i % 3) * 3.5,
        speed: 0.015 + (i * 0.004),
        angle: (i / AGENT_COUNT) * Math.PI * 2,
        inclination: (i * 0.4) - 1.2,
      });
    }

    // 6. Stardust Particle Nebula
    const PARTICLE_COUNT = 90;
    const particlePositions = new Float32Array(PARTICLE_COUNT * 3);
    const particleColors = new Float32Array(PARTICLE_COUNT * 3);

    for (let i = 0; i < PARTICLE_COUNT; i++) {
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(Math.random() * 2 - 1);
      const r = 16 + Math.random() * 14;

      particlePositions[i * 3]     = r * Math.sin(phi) * Math.cos(theta);
      particlePositions[i * 3 + 1] = r * Math.sin(phi) * Math.sin(theta);
      particlePositions[i * 3 + 2] = r * Math.cos(phi);

      const isWarm = Math.random() > 0.5;
      particleColors[i * 3]     = isWarm ? 0.93 : 0.18;
      particleColors[i * 3 + 1] = isWarm ? 0.35 : 0.36;
      particleColors[i * 3 + 2] = isWarm ? 0.23 : 0.82;
    }

    const particleGeo = new THREE.BufferGeometry();
    particleGeo.setAttribute('position', new THREE.BufferAttribute(particlePositions, 3));
    particleGeo.setAttribute('color', new THREE.BufferAttribute(particleColors, 3));

    const particleMat = new THREE.PointsMaterial({
      size: 1.2,
      vertexColors: true,
      transparent: true,
      opacity: 0.55,
      blending: THREE.NormalBlending,
      depthWrite: false,
    });

    const particles = new THREE.Points(particleGeo, particleMat);
    masterGroup.add(particles);

    // ── Interaction: Pointer Drag & Hover ──────────────────────────────────────
    let isDragging = false;
    let prevPointer = { x: 0, y: 0 };
    const rotationVelocity = { x: 0, y: 0 };
    const targetRotation = { x: 0.2, y: 0.3 };

    const onPointerDown = (e) => {
      isDragging = true;
      prevPointer = { x: e.clientX, y: e.clientY };
    };

    const onPointerMove = (e) => {
      const rect = container.getBoundingClientRect();
      const normX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
      const normY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;

      if (isDragging) {
        const deltaX = e.clientX - prevPointer.x;
        const deltaY = e.clientY - prevPointer.y;
        rotationVelocity.y = deltaX * 0.008;
        rotationVelocity.x = deltaY * 0.008;
        prevPointer = { x: e.clientX, y: e.clientY };
      } else {
        // Subtle hover tilt
        targetRotation.y = normX * 0.45;
        targetRotation.x = -normY * 0.35;
      }
    };

    const onPointerUp = () => {
      isDragging = false;
    };

    container.addEventListener('pointerdown', onPointerDown);
    window.addEventListener('pointermove', onPointerMove, { passive: true });
    window.addEventListener('pointerup', onPointerUp);

    // ── Animation Loop ─────────────────────────────────────────────────────────
    let rafId;
    let time = 0;

    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const { isSearching: searching, status: curStatus } = stateRef.current;

      const baseSpeed = searching ? 0.035 : 0.008;
      time += baseSpeed;

      if (!prefersReducedMotion) {
        // Drag inertia & easing
        if (isDragging) {
          masterGroup.rotation.y += rotationVelocity.y;
          masterGroup.rotation.x += rotationVelocity.x;
        } else {
          masterGroup.rotation.y += (targetRotation.y - masterGroup.rotation.y) * 0.05 + (searching ? 0.015 : 0.003);
          masterGroup.rotation.x += (targetRotation.x - masterGroup.rotation.x) * 0.05;
        }

        // Inner geometries independent counter-rotations
        icosahedron.rotation.y = time * 0.7;
        icosahedron.rotation.z = Math.sin(time * 0.5) * 0.2;

        dodecahedron.rotation.y = -time * 0.9;
        dodecahedron.rotation.x = Math.cos(time * 0.6) * 0.25;

        ring1.rotation.z = time * 0.5;
        ring2.rotation.z = -time * 0.4;
        ring3.rotation.z = time * 0.6;

        particles.rotation.y = time * 0.2;

        // Animate 7 agent nodes along orbits
        agentNodes.forEach((node, idx) => {
          node.angle += searching ? node.speed * 2.8 : node.speed;
          const x = Math.cos(node.angle) * node.radius;
          const y = Math.sin(node.angle) * node.radius * Math.cos(node.inclination);
          const z = Math.sin(node.angle) * node.radius * Math.sin(node.inclination);
          node.mesh.position.set(x, y, z);
          const scale = 1 + Math.sin(time * 3 + idx) * 0.25;
          node.mesh.scale.set(scale, scale, scale);
        });

        // Dynamic State Glow
        if (searching) {
          const pulse = (Math.sin(time * 8) + 1) * 0.5;
          coreMat.emissiveIntensity = 0.8 + pulse * 0.8;
          coreMat.emissive.setHex(pulse > 0.5 ? 0xee5a3b : 0x2d5bd1);
          coralLight.intensity = 4 + pulse * 2;
          cobaltLight.intensity = 4 + (1 - pulse) * 2;
          emeraldLight.intensity = 0.5;
        } else if (curStatus === 'complete') {
          coreMat.emissive.setHex(0x287e5d);
          coreMat.emissiveIntensity = 0.9;
          emeraldLight.intensity = 2.5;
        } else if (curStatus === 'needs_clarification') {
          coreMat.emissive.setHex(0xf59e0b);
          coreMat.emissiveIntensity = 0.75 + Math.sin(time * 4) * 0.35;
        } else {
          coreMat.emissive.setHex(0x2d5bd1);
          coreMat.emissiveIntensity = 0.5 + Math.sin(time * 2) * 0.2;
          emeraldLight.intensity = 0;
        }
      }

      renderer.render(scene, camera);
    };

    animate();

    // ── Resize ─────────────────────────────────────────────────────────────────
    const onResize = () => {
      if (!container) return;
      const w = container.clientWidth || 340;
      const h = container.clientHeight || 360;
      camera.aspect = w / h;
      camera.updateProjectionMatrix();
      renderer.setSize(w, h);
    };
    window.addEventListener('resize', onResize);

    // ── Cleanup ────────────────────────────────────────────────────────────────
    return () => {
      cancelAnimationFrame(rafId);
      container.removeEventListener('pointerdown', onPointerDown);
      window.removeEventListener('pointermove', onPointerMove);
      window.removeEventListener('pointerup', onPointerUp);
      window.removeEventListener('resize', onResize);

      icoGeo.dispose();
      icoMat.dispose();
      dodecGeo.dispose();
      dodecMat.dispose();
      coreGeo.dispose();
      coreMat.dispose();
      nodeGeo.dispose();
      particleGeo.dispose();
      particleMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, []);

  return (
    <div
      ref={containerRef}
      className="three-hero-core"
      role="region"
      aria-label="Interactive 3D Autonomous AI Agent Core"
      style={{
        position: 'relative',
        width: '100%',
        height: '380px',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: 'grab',
        touchAction: 'none',
      }}
    >
      <div className="three-hero-core__hud" aria-hidden="true">
        <span className="three-hero-core__status-pill">
          <span className={`three-hero-core__dot ${isSearching ? 'is-searching' : status === 'complete' ? 'is-complete' : ''}`} />
          {isSearching ? '7 Agents Active in Parallel' : status === 'complete' ? 'Verified Match Ready' : '7 Autonomous Agents Active'}
        </span>
        <span className="three-hero-core__drag-hint">Drag to inspect 3D core</span>
      </div>
    </div>
  );
}
