import React, { useState, useRef } from 'react';

const DikhaoApp = () => {
  const [screen, setScreen] = useState('landing');
  const [uploadedImage, setUploadedImage] = useState(null);
  const [textInput, setTextInput] = useState('');
  const [voiceInput, setVoiceInput] = useState('');
  const [isRecording, setIsRecording] = useState(false);
  const [aiIntent, setAiIntent] = useState(null);
  const [products, setProducts] = useState([]);
  const [selectedProduct, setSelectedProduct] = useState(null);
  const [orderID, setOrderID] = useState(null);
  const [orderStatus, setOrderStatus] = useState('placed');
  const mediaRecorder = useRef(null);
  const canvasRef = useRef(null);

  // Mock AI Understanding (In production, call Make → Anthropic/OpenAI)
  const analyzeInput = async () => {
    let input = uploadedImage ? 'Image of ' + (Math.random() > 0.5 ? 'minimalist white sneaker' : 'vintage leather bag') : textInput || voiceInput;
    
    // Simulate Make → AI → Intent API
    const mockIntent = {
      category: 'fashion',
      subcategory: ['shoes', 'sneakers'].includes(input.toLowerCase()) ? 'shoes' : 'bags',
      style: 'minimalist',
      occasion: 'daily',
      budget: 5000,
      mustHave: ['comfortable', 'durable'],
      preferred: ['waterproof', 'sustainable'],
      description: input
    };
    
    setAiIntent(mockIntent);
    
    // Simulate Make → Product API → DummyJSON/Fake Store
    const mockProducts = [
      {
        id: 1,
        name: 'Premium White Sneaker',
        brand: 'StyleCraft',
        price: 4999,
        image: '🔤',
        rating: 4.8,
        stock: 12,
        features: ['Comfortable', 'Durable', 'Lightweight'],
        matchScore: 98,
        matchReasons: ['Matches minimalist style', 'Within budget', 'Highly rated'],
        whyNotAlternatives: []
      },
      {
        id: 2,
        name: 'Classic Leather Sneaker',
        brand: 'Heritage Co',
        price: 6500,
        image: '🔤',
        rating: 4.6,
        stock: 5,
        features: ['Premium Leather', 'Durable', 'Vintage'],
        matchScore: 85,
        matchReasons: ['Great style match'],
        whyNotAlternatives: ['Exceeds budget by ₹1,500', 'Lower stock']
      },
      {
        id: 3,
        name: 'Sport Performance Shoe',
        brand: 'ActiveGear',
        price: 3999,
        image: '🔤',
        rating: 4.4,
        stock: 20,
        features: ['Waterproof', 'Comfortable', 'Sporty'],
        matchScore: 72,
        matchReasons: ['Budget-friendly', 'Good stock'],
        whyNotAlternatives: ['Sports style, not minimalist', 'Lower aesthetic match']
      }
    ];
    
    setProducts(mockProducts.sort((a, b) => b.matchScore - a.matchScore));
    setScreen('intent');
  };

  const proceedToComparison = () => {
    setScreen('comparison');
  };

  const selectProduct = (product) => {
    setSelectedProduct(product);
    setScreen('constraints');
  };

  const confirmPurchase = async () => {
    // Mock purchase via Make → Mock Purchase API
    const mockOrder = {
      id: 'ORD' + Date.now(),
      product: selectedProduct,
      total: selectedProduct.price,
      tax: Math.round(selectedProduct.price * 0.18),
      shipping: 99,
      estimatedDelivery: new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toLocaleDateString(),
      paymentMethod: 'Credit Card ending in 4242',
      timestamp: new Date().toLocaleString()
    };
    
    setOrderID(mockOrder.id);
    setOrderStatus('placed');
    setScreen('success');
    
    // Simulate delivery status progression
    setTimeout(() => setOrderStatus('confirmed'), 2000);
    setTimeout(() => setOrderStatus('shipped'), 4000);
  };

  const trackOrder = () => {
    setScreen('tracking');
  };

  const resetApp = () => {
    setScreen('landing');
    setUploadedImage(null);
    setTextInput('');
    setVoiceInput('');
    setAiIntent(null);
    setProducts([]);
    setSelectedProduct(null);
    setOrderID(null);
  };

  const startVoiceRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      mediaRecorder.current = recorder;
      
      let chunks = [];
      recorder.ondataavailable = (e) => chunks.push(e.data);
      recorder.onstop = () => {
        // Simulate voice-to-text via Make → Speech-to-Text API
        setVoiceInput('Show me minimalist white sneakers');
        setIsRecording(false);
      };
      
      recorder.start();
      setIsRecording(true);
      
      setTimeout(() => {
        recorder.stop();
        stream.getTracks().forEach(track => track.stop());
      }, 3000);
    } catch (err) {
      console.error('Microphone access denied');
    }
  };

  const handleImageUpload = (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onload = (event) => {
        setUploadedImage(event.target.result);
      };
      reader.readAsDataURL(file);
    }
  };

  // SCREEN 1: Landing
  if (screen === 'landing') {
    return (
      <div style={{ background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', fontFamily: 'sans-serif' }}>
        <div style={{ textAlign: 'center', maxWidth: '600px' }}>
          <h1 style={{ fontSize: '48px', fontWeight: 'bold', color: 'white', margin: '0 0 20px' }}>Dikhao</h1>
          <p style={{ fontSize: '24px', color: 'rgba(255,255,255,0.9)', margin: '0 0 30px' }}>Show what inspires you. We'll find what to buy.</p>
          <p style={{ fontSize: '16px', color: 'rgba(255,255,255,0.8)', margin: '0 0 40px', lineHeight: '1.6' }}>Upload an image from Instagram, describe what you want, or speak it out. Our AI understands your style and finds the perfect product.</p>
          
          <button onClick={() => setScreen('input')} style={{ padding: '16px 40px', fontSize: '18px', fontWeight: '600', background: 'white', color: '#667eea', border: 'none', borderRadius: '8px', cursor: 'pointer', boxShadow: '0 10px 30px rgba(0,0,0,0.2)' }}>
            Start Shopping
          </button>
        </div>
      </div>
    );
  }

  // SCREEN 2: Upload/Voice/Text Input
  if (screen === 'input') {
    return (
      <div style={{ background: '#f5f5f5', minHeight: '100vh', padding: '40px 20px', fontFamily: 'sans-serif' }}>
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '10px' }}>Tell us what inspires you</h2>
          <p style={{ color: '#666', marginBottom: '40px' }}>Upload an image, describe it, or record your voice</p>

          {/* Image Upload */}
          <div style={{ background: 'white', padding: '30px', borderRadius: '12px', border: '2px dashed #ddd', textAlign: 'center', marginBottom: '30px', cursor: 'pointer', transition: 'all 0.3s' }} onMouseEnter={(e) => e.target.style.borderColor = '#667eea'} onMouseLeave={(e) => e.target.style.borderColor = '#ddd'}>
            <input type="file" accept="image/*" onChange={handleImageUpload} style={{ display: 'none' }} id="image-input" />
            <label htmlFor="image-input" style={{ cursor: 'pointer', display: 'block' }}>
              {uploadedImage ? (
                <div>
                  <img src={uploadedImage} alt="Uploaded" style={{ maxHeight: '200px', maxWidth: '100%', borderRadius: '8px' }} />
                  <p style={{ marginTop: '10px', color: '#667eea', fontWeight: '600' }}>Click to change image</p>
                </div>
              ) : (
                <div>
                  <div style={{ fontSize: '40px', marginBottom: '10px' }}>📸</div>
                  <p style={{ fontSize: '16px', fontWeight: '600', margin: '0 0 5px', color: '#333' }}>Upload an image</p>
                  <p style={{ fontSize: '14px', color: '#999', margin: '0' }}>From Instagram, Pinterest, or your camera</p>
                </div>
              )}
            </label>
          </div>

          {/* Text Input */}
          <div style={{ marginBottom: '30px' }}>
            <p style={{ marginBottom: '10px', fontWeight: '600', color: '#333' }}>Or describe what you want</p>
            <textarea placeholder="E.g., minimalist white sneakers, durable leather bag..." value={textInput} onChange={(e) => setTextInput(e.target.value)} style={{ width: '100%', padding: '12px', fontSize: '16px', border: '1px solid #ddd', borderRadius: '8px', fontFamily: 'sans-serif', minHeight: '100px', boxSizing: 'border-box' }} />
          </div>

          {/* Voice Input */}
          <div style={{ marginBottom: '30px' }}>
            <p style={{ marginBottom: '10px', fontWeight: '600', color: '#333' }}>Or record your voice</p>
            <button onClick={startVoiceRecording} disabled={isRecording} style={{ padding: '12px 24px', fontSize: '16px', background: isRecording ? '#ccc' : '#667eea', color: 'white', border: 'none', borderRadius: '8px', cursor: isRecording ? 'not-allowed' : 'pointer', width: '100%' }}>
              {isRecording ? '🎤 Recording... (3s)' : '🎤 Record voice'}
            </button>
            {voiceInput && <p style={{ marginTop: '10px', color: '#667eea', fontSize: '14px' }}>✓ Heard: "{voiceInput}"</p>}
          </div>

          {/* Action Buttons */}
          <div style={{ display: 'flex', gap: '12px' }}>
            <button onClick={analyzeInput} disabled={!uploadedImage && !textInput && !voiceInput} style={{ flex: 1, padding: '14px', fontSize: '16px', fontWeight: '600', background: '#667eea', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', opacity: (!uploadedImage && !textInput && !voiceInput) ? 0.5 : 1 }}>
              Find Products
            </button>
            <button onClick={resetApp} style={{ flex: 1, padding: '14px', fontSize: '16px', fontWeight: '600', background: '#f0f0f0', color: '#333', border: '1px solid #ddd', borderRadius: '8px', cursor: 'pointer' }}>
              Cancel
            </button>
          </div>
        </div>
      </div>
    );
  }

  // SCREEN 3: AI Understanding
  if (screen === 'intent') {
    return (
      <div style={{ background: '#f5f5f5', minHeight: '100vh', padding: '40px 20px', fontFamily: 'sans-serif' }}>
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '10px' }}>Here's what we understand</h2>
          <p style={{ color: '#666', marginBottom: '30px' }}>AI analyzed your request and found {products.length} matching products</p>

          {aiIntent && (
            <div style={{ background: 'white', padding: '24px', borderRadius: '12px', marginBottom: '30px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '20px' }}>
                <div>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>CATEGORY</p>
                  <p style={{ fontSize: '16px', fontWeight: '600', margin: '0', color: '#333' }}>{aiIntent.category}</p>
                </div>
                <div>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>STYLE</p>
                  <p style={{ fontSize: '16px', fontWeight: '600', margin: '0', color: '#333' }}>{aiIntent.style}</p>
                </div>
                <div>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>BUDGET</p>
                  <p style={{ fontSize: '16px', fontWeight: '600', margin: '0', color: '#333' }}>₹{aiIntent.budget.toLocaleString()}</p>
                </div>
                <div>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>OCCASION</p>
                  <p style={{ fontSize: '16px', fontWeight: '600', margin: '0', color: '#333' }}>{aiIntent.occasion}</p>
                </div>
              </div>
              
              <div style={{ borderTop: '1px solid #eee', paddingTop: '16px' }}>
                <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 8px' }}>MUST-HAVE</p>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
                  {aiIntent.mustHave.map((item, i) => (
                    <span key={i} style={{ background: '#667eea', color: 'white', padding: '4px 12px', borderRadius: '20px', fontSize: '12px', fontWeight: '600' }}>✓ {item}</span>
                  ))}
                </div>
                
                <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 8px' }}>PREFERRED</p>
                <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                  {aiIntent.preferred.map((item, i) => (
                    <span key={i} style={{ background: '#f0f0f0', color: '#666', padding: '4px 12px', borderRadius: '20px', fontSize: '12px' }}>◇ {item}</span>
                  ))}
                </div>
              </div>
            </div>
          )}

          <button onClick={proceedToComparison} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#667eea', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', marginBottom: '12px' }}>
            Compare {products.length} Products
          </button>
          <button onClick={resetApp} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#f0f0f0', color: '#333', border: '1px solid #ddd', borderRadius: '8px', cursor: 'pointer' }}>
            Start Over
          </button>
        </div>
      </div>
    );
  }

  // SCREEN 4: Product Comparison
  if (screen === 'comparison') {
    return (
      <div style={{ background: '#f5f5f5', minHeight: '100vh', padding: '40px 20px', fontFamily: 'sans-serif' }}>
        <div style={{ maxWidth: '800px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '10px' }}>Ranked by match score</h2>
          <p style={{ color: '#666', marginBottom: '30px' }}>Sorted by how well each product matches your style and budget</p>

          {products.map((product, index) => (
            <div key={product.id} style={{ background: 'white', padding: '24px', borderRadius: '12px', marginBottom: '16px', border: index === 0 ? '2px solid #667eea' : '1px solid #ddd' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: '16px' }}>
                <div style={{ flex: 1 }}>
                  {index === 0 && <p style={{ color: '#667eea', fontSize: '12px', fontWeight: '600', margin: '0 0 4px' }}>BEST MATCH</p>}
                  <p style={{ fontSize: '18px', fontWeight: '600', margin: '0 0 4px', color: '#333' }}>{product.name}</p>
                  <p style={{ fontSize: '13px', color: '#999', margin: '0' }}>{product.brand}</p>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <p style={{ fontSize: '28px', fontWeight: 'bold', color: '#667eea', margin: '0' }}>₹{product.price.toLocaleString()}</p>
                  <p style={{ fontSize: '12px', color: '#999', margin: '4px 0 0' }}>⭐ {product.rating}/5</p>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px', marginBottom: '16px' }}>
                <div>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 8px' }}>MATCH SCORE</p>
                  <div style={{ background: '#f0f0f0', height: '8px', borderRadius: '4px', overflow: 'hidden' }}>
                    <div style={{ background: '#667eea', height: '100%', width: product.matchScore + '%' }} />
                  </div>
                  <p style={{ fontSize: '13px', fontWeight: '600', margin: '4px 0 0', color: '#333' }}>{product.matchScore}%</p>
                </div>
                <div>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 8px' }}>STOCK</p>
                  <p style={{ fontSize: '16px', fontWeight: '600', color: product.stock > 5 ? '#22c55e' : '#f97316' }}>{product.stock} available</p>
                </div>
              </div>

              <div style={{ marginBottom: '16px' }}>
                <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 8px' }}>WHY THIS MATCHES</p>
                <ul style={{ margin: '0', paddingLeft: '20px', fontSize: '13px' }}>
                  {product.matchReasons.map((reason, i) => (
                    <li key={i} style={{ color: '#22c55e', marginBottom: '4px' }}>✓ {reason}</li>
                  ))}
                </ul>
              </div>

              {product.whyNotAlternatives.length > 0 && (
                <div style={{ marginBottom: '16px', background: '#f9fafb', padding: '12px', borderRadius: '8px' }}>
                  <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 8px' }}>WHY NOT ALTERNATIVES</p>
                  <ul style={{ margin: '0', paddingLeft: '20px', fontSize: '13px' }}>
                    {product.whyNotAlternatives.map((reason, i) => (
                      <li key={i} style={{ color: '#f97316', marginBottom: '4px' }}>✗ {reason}</li>
                    ))}
                  </ul>
                </div>
              )}

              <button onClick={() => selectProduct(product)} style={{ width: '100%', padding: '12px', fontSize: '14px', fontWeight: '600', background: '#667eea', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
                Check constraints
              </button>
            </div>
          ))}

          <button onClick={resetApp} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#f0f0f0', color: '#333', border: '1px solid #ddd', borderRadius: '8px', cursor: 'pointer', marginTop: '20px' }}>
            Start Over
          </button>
        </div>
      </div>
    );
  }

  // SCREEN 5: Constraint Proof
  if (screen === 'constraints' && selectedProduct) {
    const verifyConstraints = [
      { name: 'Budget', status: selectedProduct.price <= aiIntent.budget, value: `₹${selectedProduct.price} ≤ ₹${aiIntent.budget}` },
      { name: 'In Stock', status: selectedProduct.stock > 0, value: `${selectedProduct.stock} units available` },
      { name: 'Availability', status: true, value: 'Ships within 2-3 days' },
      { name: 'Must-have Features', status: true, value: selectedProduct.features.filter(f => aiIntent.mustHave.some(m => f.toLowerCase().includes(m.toLowerCase()))).join(', ') }
    ];

    return (
      <div style={{ background: '#f5f5f5', minHeight: '100vh', padding: '40px 20px', fontFamily: 'sans-serif' }}>
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '10px' }}>Constraint verification</h2>
          <p style={{ color: '#666', marginBottom: '30px' }}>All hard constraints verified before purchase</p>

          <div style={{ background: 'white', borderRadius: '12px', overflow: 'hidden', marginBottom: '30px' }}>
            {verifyConstraints.map((constraint, i) => (
              <div key={i} style={{ padding: '16px', borderBottom: i < verifyConstraints.length - 1 ? '1px solid #eee' : 'none', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <div>
                  <p style={{ fontSize: '14px', fontWeight: '600', margin: '0 0 4px', color: '#333' }}>{constraint.name}</p>
                  <p style={{ fontSize: '13px', color: '#999', margin: '0' }}>{constraint.value}</p>
                </div>
                <span style={{ fontSize: '20px' }}>{constraint.status ? '✅' : '❌'}</span>
              </div>
            ))}
          </div>

          <div style={{ background: '#f0fdf4', border: '1px solid #86efac', padding: '16px', borderRadius: '8px', marginBottom: '30px' }}>
            <p style={{ margin: '0', color: '#166534', fontSize: '14px', fontWeight: '600' }}>✓ All constraints satisfied. Safe to purchase.</p>
          </div>

          <div style={{ background: 'white', padding: '20px', borderRadius: '12px', marginBottom: '30px' }}>
            <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 12px' }}>ORDER SUMMARY</p>
            <div style={{ fontSize: '14px', marginBottom: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                <span style={{ color: '#666' }}>{selectedProduct.name}</span>
                <span style={{ fontWeight: '600' }}>₹{selectedProduct.price.toLocaleString()}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px', color: '#999', fontSize: '13px' }}>
                <span>Tax (18%)</span>
                <span>₹{Math.round(selectedProduct.price * 0.18).toLocaleString()}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px', color: '#999', fontSize: '13px' }}>
                <span>Shipping</span>
                <span>₹99</span>
              </div>
              <div style={{ borderTop: '1px solid #eee', paddingTop: '12px', display: 'flex', justifyContent: 'space-between', fontSize: '16px', fontWeight: 'bold', color: '#333' }}>
                <span>Total</span>
                <span>₹{(selectedProduct.price + Math.round(selectedProduct.price * 0.18) + 99).toLocaleString()}</span>
              </div>
            </div>
          </div>

          <button onClick={confirmPurchase} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#22c55e', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', marginBottom: '12px' }}>
            Confirm purchase
          </button>
          <button onClick={() => setScreen('comparison')} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#f0f0f0', color: '#333', border: '1px solid #ddd', borderRadius: '8px', cursor: 'pointer' }}>
            Back to comparison
          </button>
        </div>
      </div>
    );
  }

  // SCREEN 6: Purchase Confirmation
  if (screen === 'success' && orderID) {
    return (
      <div style={{ background: '#f0fdf4', minHeight: '100vh', display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '20px', fontFamily: 'sans-serif' }}>
        <div style={{ background: 'white', borderRadius: '12px', padding: '40px', maxWidth: '500px', textAlign: 'center', boxShadow: '0 10px 30px rgba(0,0,0,0.1)' }}>
          <div style={{ fontSize: '80px', marginBottom: '20px' }}>
            {orderStatus === 'placed' && '✅'}
            {orderStatus === 'confirmed' && '📦'}
            {orderStatus === 'shipped' && '🚚'}
          </div>
          
          <h2 style={{ fontSize: '28px', fontWeight: 'bold', color: '#22c55e', margin: '0 0 10px' }}>
            {orderStatus === 'placed' && 'Order placed!'}
            {orderStatus === 'confirmed' && 'Order confirmed!'}
            {orderStatus === 'shipped' && 'Order shipped!'}
          </h2>
          
          <p style={{ color: '#666', margin: '0 0 30px', fontSize: '14px', lineHeight: '1.6' }}>
            Your order has been {orderStatus}. You'll receive it within 2-3 days.
          </p>

          <div style={{ background: '#f9fafb', padding: '20px', borderRadius: '8px', marginBottom: '30px', textAlign: 'left' }}>
            <div style={{ marginBottom: '16px' }}>
              <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>ORDER ID</p>
              <p style={{ fontSize: '16px', fontWeight: 'bold', color: '#333', margin: '0', fontFamily: 'monospace' }}>{orderID}</p>
            </div>
            <div style={{ marginBottom: '16px' }}>
              <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>PRODUCT</p>
              <p style={{ fontSize: '14px', color: '#333', margin: '0' }}>{selectedProduct.name}</p>
            </div>
            <div>
              <p style={{ fontSize: '12px', color: '#999', fontWeight: '600', margin: '0 0 4px' }}>ESTIMATED DELIVERY</p>
              <p style={{ fontSize: '14px', color: '#333', margin: '0' }}>{new Date(Date.now() + 3 * 24 * 60 * 60 * 1000).toLocaleDateString()}</p>
            </div>
          </div>

          <button onClick={trackOrder} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#667eea', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer', marginBottom: '12px' }}>
            Track order
          </button>
          <button onClick={resetApp} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#f0f0f0', color: '#333', border: '1px solid #ddd', borderRadius: '8px', cursor: 'pointer' }}>
            Shop again
          </button>
        </div>
      </div>
    );
  }

  // SCREEN 7: Order Tracking
  if (screen === 'tracking' && orderID) {
    const trackingSteps = [
      { status: 'Order Placed', time: 'Just now', completed: true },
      { status: 'Payment Confirmed', time: '2 mins ago', completed: orderStatus !== 'placed' },
      { status: 'Preparing to Ship', time: 'In progress', completed: orderStatus === 'shipped' },
      { status: 'Out for Delivery', time: 'Estimated tomorrow', completed: false }
    ];

    return (
      <div style={{ background: '#f5f5f5', minHeight: '100vh', padding: '40px 20px', fontFamily: 'sans-serif' }}>
        <div style={{ maxWidth: '600px', margin: '0 auto' }}>
          <h2 style={{ fontSize: '28px', fontWeight: 'bold', marginBottom: '10px' }}>Order tracking</h2>
          <p style={{ color: '#666', marginBottom: '30px' }}>Order {orderID}</p>

          <div style={{ background: 'white', borderRadius: '12px', padding: '30px', marginBottom: '30px' }}>
            {trackingSteps.map((step, i) => (
              <div key={i} style={{ display: 'flex', marginBottom: i < trackingSteps.length - 1 ? '24px' : '0' }}>
                <div style={{ marginRight: '20px', display: 'flex', flexDirection: 'column', alignItems: 'center' }}>
                  <div style={{ width: '24px', height: '24px', borderRadius: '50%', background: step.completed ? '#22c55e' : '#e5e7eb', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'white', fontWeight: 'bold', fontSize: '12px' }}>
                    {step.completed ? '✓' : i + 1}
                  </div>
                  {i < trackingSteps.length - 1 && <div style={{ width: '2px', height: '40px', background: step.completed ? '#22c55e' : '#e5e7eb', margin: '8px 0' }} />}
                </div>
                <div>
                  <p style={{ fontSize: '14px', fontWeight: '600', color: '#333', margin: '0 0 4px' }}>{step.status}</p>
                  <p style={{ fontSize: '13px', color: '#999', margin: '0' }}>{step.time}</p>
                </div>
              </div>
            ))}
          </div>

          <div style={{ background: '#e0e7ff', border: '1px solid #c7d2fe', padding: '16px', borderRadius: '8px', marginBottom: '30px' }}>
            <p style={{ margin: '0', color: '#3730a3', fontSize: '14px', fontWeight: '600' }}>💬 We'll notify you when your order ships!</p>
          </div>

          <button onClick={resetApp} style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600', background: '#667eea', color: 'white', border: 'none', borderRadius: '8px', cursor: 'pointer' }}>
            Continue shopping
          </button>
        </div>
      </div>
    );
  }
};

export default DikhaoApp;
