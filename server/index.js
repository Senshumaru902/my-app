const express = require("express");
const multer = require("multer");
const fs = require("fs");
const cors = require("cors");
const path = require("path");

const app = express();
const PORT = process.env.PORT || 5000;

// Permitir requisições do frontend
app.use(cors());

// Criar pasta temporária se não existir
const tmpDir = path.join(__dirname, "tmp");
if (!fs.existsSync(tmpDir)) {
  fs.mkdirSync(tmpDir);
}

// Configuração do Multer para pasta temporária
const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    cb(null, tmpDir);
  },
  filename: (req, file, cb) => {
    cb(null, `${Date.now()}-${file.originalname}`);
  },
});

// Limitar tipo de arquivo opcionalmente
const fileFilter = (req, file, cb) => {
  // Aceita vídeos e imagens
  if (file.mimetype.startsWith("video/") || file.mimetype.startsWith("image/")) {
    cb(null, true);
  } else {
    cb(new Error("Apenas vídeos ou imagens são permitidos"), false);
  }
};

const upload = multer({ storage, fileFilter });

// Endpoint para receber upload
app.post("/upload", upload.single("file"), (req, res) => {
  if (!req.file) {
    return res.status(400).send("Nenhum arquivo enviado");
  }

  console.log("Arquivo recebido:", req.file.originalname);
  console.log("Caminho temporário:", req.file.path);

  // Retornar info para o frontend
  res.json({ message: "Arquivo recebido com sucesso!", filename: req.file.filename });

  // Deletar arquivo após 1 minuto
  setTimeout(() => {
    fs.unlink(req.file.path, (err) => {
      if (err) console.error("Erro ao deletar arquivo:", err);
      else console.log("Arquivo temporário deletado:", req.file.filename);
    });
  }, 60000); // 1 minuto
});

app.listen(PORT, () => {
  console.log(`Servidor de upload rodando em http://localhost:${PORT}`);
});
