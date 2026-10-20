<?php
/**
 * Cliente do servico de OCR (ocr_server.py) para o SysMG.
 *
 * Uso:
 *   require_once 'OcrClient.php';
 *   $ocr = new OcrClient('https://ocr.seudominio.com.br', getenv('OCR_API_TOKEN'));
 *
 *   $r = $ocr->ocr('/caminho/extrato.pdf');
 *   echo $r['texto'];               // texto de todas as paginas
 *   echo $r['paginas_ocr'];         // quantas paginas passaram pelo Tesseract
 *
 *   $r = $ocr->extrato('/caminho/extrato.pdf', '01/01/2020', '31/12/2020', 'TODOS OS LANÇAMENTOS');
 *   echo $r['prompt_forense'];      // prompt mestre com o texto embutido
 *
 * Em caso de falha lanca RuntimeException com a mensagem do servidor.
 */
class OcrClient
{
    private $baseUrl;
    private $token;
    private $timeout;

    /**
     * @param string $baseUrl  Endereco do servico (ex.: https://ocr.seudominio.com.br)
     * @param string $token    Mesmo valor de OCR_API_TOKEN configurado na VPS
     * @param int    $timeout  Segundos de espera pela resposta (extratos longos demoram)
     */
    public function __construct($baseUrl, $token, $timeout = 900)
    {
        $this->baseUrl = rtrim($baseUrl, '/');
        $this->token = $token;
        $this->timeout = $timeout;
    }

    public function health()
    {
        return $this->requisitar('/health');
    }

    public function ocr($caminhoPdf)
    {
        return $this->requisitar('/ocr', array('file' => $this->arquivo($caminhoPdf)));
    }

    public function extrato($caminhoPdf, $dataInicio = null, $dataFim = null, $filtro = null)
    {
        $campos = array('file' => $this->arquivo($caminhoPdf));
        if ($dataInicio !== null) {
            $campos['data_inicio'] = $dataInicio;
        }
        if ($dataFim !== null) {
            $campos['data_fim'] = $dataFim;
        }
        if ($filtro !== null) {
            $campos['filtro'] = $filtro;
        }
        return $this->requisitar('/extrato', $campos);
    }

    private function arquivo($caminhoPdf)
    {
        if (!is_file($caminhoPdf)) {
            throw new RuntimeException("PDF nao encontrado: $caminhoPdf");
        }
        // O servidor exige nome terminado em .pdf
        $nome = basename($caminhoPdf);
        if (strtolower(substr($nome, -4)) !== '.pdf') {
            $nome .= '.pdf';
        }
        return new CURLFile($caminhoPdf, 'application/pdf', $nome);
    }

    /** GET quando $campos e null; POST multipart caso contrario. */
    private function requisitar($rota, $campos = null)
    {
        $ch = curl_init($this->baseUrl . $rota);
        curl_setopt_array($ch, array(
            CURLOPT_RETURNTRANSFER => true,
            CURLOPT_HTTPHEADER => array('Authorization: Bearer ' . $this->token),
            CURLOPT_CONNECTTIMEOUT => 10,
            CURLOPT_TIMEOUT => $this->timeout,
        ));
        if ($campos !== null) {
            curl_setopt($ch, CURLOPT_POST, true);
            curl_setopt($ch, CURLOPT_POSTFIELDS, $campos);
        }

        $corpo = curl_exec($ch);
        if ($corpo === false) {
            throw new RuntimeException('Falha de conexao com o servico de OCR: ' . curl_error($ch));
        }
        $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
        $dados = json_decode($corpo, true);

        if ($status !== 200) {
            $msg = isset($dados['erro']) ? $dados['erro'] : "HTTP $status";
            throw new RuntimeException("Servico de OCR recusou a requisicao: $msg");
        }
        if (!is_array($dados)) {
            throw new RuntimeException('Resposta invalida do servico de OCR.');
        }
        return $dados;
    }
}
