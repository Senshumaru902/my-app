import React, { useState, useRef, useEffect } from "react";
import { FiUpload, FiCamera } from "react-icons/fi";

export default function Chat() {
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState("");
  const messagesEndRef = useRef(null);
  const [firstMessageSent, setFirstMessageSent] = useState(false);
  const sendSound = "/send.mp3";

  // Webcam
  const [stream, setStream] = useState(null);
  const videoRef = useRef(null);
  const [expanded, setExpanded] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [position, setPosition] = useState({ top: 100, left: 100 });
  const offsetRef = useRef({ x: 0, y: 0 });

  const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || "http://localhost:5000";

  // Scroll automático
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    if (videoRef.current && stream) {
      videoRef.current.srcObject = stream;
    }
  }, [stream]);

  const playSound = (sound) => {
    const audio = new Audio(sound);
    audio.play();
  };

  // Enviar mensagem
  const sendMessage = (text = input) => {
    if (!text.trim()) return;

    setMessages([...messages, { text, fromUser: true }]);
    playSound(sendSound);
    setInput("");

    if (!firstMessageSent) {
      setFirstMessageSent(true);
      setTimeout(() => {
        setMessages((prev) => [
          ...prev,
          {
            text: "🌸 Oi! Que tal começarmos com algo leve? Prefere conversar sobre Filmes, Séries, Música ou Viagens? 🌷",
            fromUser: false,
          },
        ]);
      }, 500);
    }
  };

  // Upload de arquivos
  const handleFileUpload = async (event) => {
    const file = event.target.files[0];
    if (!file) return;

    if (file.size > 50 * 1024 * 1024) {
      alert("Arquivo muito grande! Máx: 50MB");
      return;
    }

    const formData = new FormData();
    formData.append("file", file);

    setMessages((prev) => [...prev, { text: `⬆️ Enviando "${file.name}"...`, fromUser: true }]);

    try {
      const res = await fetch(`${BACKEND_URL}/upload`, {
        method: "POST",
        body: formData,
      });

      if (!res.ok) {
        const errorText = await res.text();
        throw new Error(errorText);
      }

      const data = await res.json();
      setMessages((prev) => [
        ...prev,
        { text: `📁 Arquivo "${file.name}" enviado com sucesso!`, fromUser: false },
      ]);
    } catch (err) {
      console.error(err);
      setMessages((prev) => [
        ...prev,
        { text: `❌ Erro ao enviar "${file.name}": ${err.message}`, fromUser: false },
      ]);
    }
  };

  // Webcam
  const handleStartCamera = async () => {
    try {
      const mediaStream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      setStream(mediaStream);
      setMessages((prev) => [...prev, { text: "📹 Webcam ativada!", fromUser: false }]);
    } catch (err) {
      console.error(err);
      setMessages((prev) => [...prev, { text: "❌ Não foi possível acessar a webcam.", fromUser: false }]);
    }
  };

  const handleStopCamera = () => {
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      setStream(null);
      setExpanded(false);
      setMessages((prev) => [...prev, { text: "❌ Webcam desligada.", fromUser: false }]);
    }
  };

  // Drag da webcam
  const handleMouseDown = (e) => {
    setDragging(true);
    offsetRef.current = { x: e.clientX - position.left, y: e.clientY - position.top };
  };

  const handleMouseMove = (e) => {
    if (!dragging) return;
    setPosition({ left: e.clientX - offsetRef.current.x, top: e.clientY - offsetRef.current.y });
  };

  const handleMouseUp = () => setDragging(false);

  useEffect(() => {
    window.addEventListener("mousemove", handleMouseMove);
    window.addEventListener("mouseup", handleMouseUp);
    return () => {
      window.removeEventListener("mousemove", handleMouseMove);
      window.removeEventListener("mouseup", handleMouseUp);
    };
  });

  return (
    <div className="chat-container">
      {/* Mensagens */}
      <div className="chat-messages">
        {messages.map((msg, idx) => (
          <div className={`message ${msg.fromUser ? "user" : "bot"}`} key={idx}>
            <div
              className={`message-bubble ${msg.fromUser ? "user" : "bot"}`}
              style={{ animation: "fadeSlide 0.5s forwards", transition: "all 0.5s ease" }}
            >
              {msg.text}
            </div>
          </div>
        ))}
        <div ref={messagesEndRef}></div>
      </div>

      {/* Webcam flutuante */}
      {stream && (
        <div
          onMouseDown={handleMouseDown}
          style={{
            position: "fixed",
            top: position.top,
            left: position.left,
            width: expanded ? "400px" : "200px",
            height: expanded ? "300px" : "150px",
            borderRadius: "12px",
            border: "1px solid rgba(255,255,255,0.3)",
            cursor: "move",
            background: "#000",
            zIndex: 1000,
            transition: "width 0.3s, height 0.3s",
          }}
        >
          <video
            ref={videoRef}
            autoPlay
            playsInline
            style={{ width: "100%", height: "100%", borderRadius: "12px", objectFit: "cover" }}
          />
          <div style={{ position: "absolute", top: 5, right: 5, display: "flex", gap: "5px" }}>
            <button
              onClick={() => setExpanded(!expanded)}
              style={{ background: "rgba(255,255,255,0.7)", border: "none", borderRadius: "50%", cursor: "pointer" }}
            >
              {expanded ? "−" : "+"}
            </button>
            <button
              onClick={handleStopCamera}
              style={{ background: "rgba(255,255,255,0.7)", border: "none", borderRadius: "50%", cursor: "pointer" }}
            >
              ✕
            </button>
          </div>
        </div>
      )}

      {/* Input e ícones */}
      <div style={{ display: "flex", alignItems: "center", marginTop: "10px", position: "relative" }}>
        <label htmlFor="fileUpload" style={{ position: "absolute", left: "10px", cursor: "pointer", color: "#007bff", zIndex: 10 }}>
          <FiUpload size={28} />
          <input id="fileUpload" type="file" accept="video/*,image/*" style={{ display: "none" }} onChange={handleFileUpload} />
        </label>

        <button
          onClick={stream ? handleStopCamera : handleStartCamera}
          style={{ position: "absolute", left: "40px", background: "transparent", border: "none", cursor: "pointer", color: stream ? "#dc3545" : "#28a745", zIndex: 10 }}
        >
          <FiCamera size={28} />
        </button>

        <input
          className="chat-input"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="Digite sua mensagem..."
          onKeyDown={(e) => {
            if (e.key === "Enter") sendMessage();
          }}
          style={{
            flex: 1,
            paddingLeft: "70px",
            borderRadius: "16px",
            border: "1px solid rgba(255,255,255,0.3)",
            background: "rgba(255,255,255,0.1)",
            height: "40px",
            zIndex: 1,
          }}
        />
      </div>
    </div>
  );
}
