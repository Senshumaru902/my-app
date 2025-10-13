import React from "react";

export default function Poll({ topics, onSelect }) {
  return (
    <div style={{ marginBottom: "15px" }}>
      <h3 style={{ marginBottom: "10px", color: "#333" }}>Escolha um assunto:</h3>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "10px" }}>
        {topics.map((topic, idx) => (
          <button
            key={idx}
            onClick={() => onSelect(topic)}
            style={{
              padding: "8px 12px",
              borderRadius: "16px",
              border: "none",
              backgroundColor: "#0084ff",
              color: "#fff",
              cursor: "pointer",
              transition: "transform 0.2s",
            }}
            onMouseEnter={(e) => (e.currentTarget.style.transform = "scale(1.05)")}
            onMouseLeave={(e) => (e.currentTarget.style.transform = "scale(1)")}
          >
            {topic}
          </button>
        ))}
      </div>
    </div>
  );
}
