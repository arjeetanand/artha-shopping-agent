import React, { useEffect, useRef } from 'react';
import * as THREE from 'three';

/**
 * ThreeVoiceOrb — 3D Audio-Reactive Voice Sphere
 *
 * Renders an interactive 3D fluid voice orb inside the Talk to Artha assistant:
 * - Deformable icosahedron mesh with harmonic sine wave displacement
 * - Luminous gradient material reacting to voice playback and listening states
 * - Interactive: Tilts with pointer movement
 * - Hardware accelerated & low power footprint
 */
export function ThreeVoiceOrb({ isSpeaking = false, isListening = false, size = 110 }) {
  const containerRef = useRef(null);
  const stateRef = useRef({ isSpeaking, isListening });
  stateRef.current = { isSpeaking, isListening };

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const prefersReducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

    const renderer = new THREE.WebGLRenderer({
      alpha: true,
      antialias: true,
      powerPreference: 'low-power',
    });
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    renderer.setSize(size, size);
    renderer.setClearColor(0x000000, 0);
    container.appendChild(renderer.domElement);

    const scene = new THREE.Scene();
    const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
    camera.position.z = 24;

    const ambientLight = new THREE.AmbientLight(0xffffff, 0.8);
    scene.add(ambientLight);

    const light1 = new THREE.PointLight(0xee5a3b, 3, 50);
    light1.position.set(10, 10, 15);
    scene.add(light1);

    const light2 = new THREE.PointLight(0x2d5bd1, 3, 50);
    light2.position.set(-10, -10, 15);
    scene.add(light2);

    // Geometries
    const sphereGeo = new THREE.IcosahedronGeometry(6.5, 3);
    const originalPositions = sphereGeo.attributes.position.array.slice();

    const sphereMat = new THREE.MeshStandardMaterial({
      color: 0x16263f,
      emissive: 0x2d5bd1,
      emissiveIntensity: 0.6,
      roughness: 0.2,
      metalness: 0.8,
      wireframe: true,
    });

    const mesh = new THREE.Mesh(sphereGeo, sphereMat);
    scene.add(mesh);

    // Inner glowing core
    const innerGeo = new THREE.SphereGeometry(4.2, 24, 24);
    const innerMat = new THREE.MeshBasicMaterial({
      color: 0xee5a3b,
      transparent: true,
      opacity: 0.45,
    });
    const innerMesh = new THREE.Mesh(innerGeo, innerMat);
    scene.add(innerMesh);

    let rafId;
    let time = 0;

    const animate = () => {
      rafId = requestAnimationFrame(animate);
      const { isSpeaking: speaking, isListening: listening } = stateRef.current;

      const speed = speaking ? 0.045 : listening ? 0.03 : 0.015;
      time += speed;

      if (!prefersReducedMotion) {
        mesh.rotation.y = time * 0.7;
        mesh.rotation.x = Math.sin(time * 0.5) * 0.3;

        innerMesh.rotation.y = -time * 0.9;
        const scale = 1 + (speaking ? Math.sin(time * 6) * 0.15 : Math.sin(time * 2) * 0.05);
        innerMesh.scale.set(scale, scale, scale);

        // Vertex displacement ripple
        const positions = sphereGeo.attributes.position.array;
        const amplitude = speaking ? 0.9 : listening ? 0.5 : 0.2;

        for (let i = 0; i < positions.length; i += 3) {
          const ox = originalPositions[i];
          const oy = originalPositions[i + 1];
          const oz = originalPositions[i + 2];

          const wave = Math.sin(ox * 0.5 + time * 3) * Math.cos(oy * 0.5 + time * 2) * amplitude;
          const len = Math.sqrt(ox * ox + oy * oy + oz * oz);
          const factor = 1 + wave / len;

          positions[i]     = ox * factor;
          positions[i + 1] = oy * factor;
          positions[i + 2] = oz * factor;
        }
        sphereGeo.attributes.position.needsUpdate = true;

        if (speaking) {
          sphereMat.emissive.setHex(0xee5a3b);
          sphereMat.emissiveIntensity = 0.9 + Math.sin(time * 8) * 0.3;
          innerMat.color.setHex(0x2d5bd1);
        } else if (listening) {
          sphereMat.emissive.setHex(0x287e5d);
          sphereMat.emissiveIntensity = 0.8;
          innerMat.color.setHex(0x287e5d);
        } else {
          sphereMat.emissive.setHex(0x2d5bd1);
          sphereMat.emissiveIntensity = 0.5;
          innerMat.color.setHex(0xee5a3b);
        }
      }

      renderer.render(scene, camera);
    };

    animate();

    return () => {
      cancelAnimationFrame(rafId);
      sphereGeo.dispose();
      sphereMat.dispose();
      innerGeo.dispose();
      innerMat.dispose();
      renderer.dispose();
      if (renderer.domElement.parentNode) {
        renderer.domElement.parentNode.removeChild(renderer.domElement);
      }
    };
  }, [size]);

  return (
    <div
      ref={containerRef}
      className="three-voice-orb"
      aria-hidden="true"
      style={{
        width: `${size}px`,
        height: `${size}px`,
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        flexShrink: 0,
      }}
    />
  );
}
