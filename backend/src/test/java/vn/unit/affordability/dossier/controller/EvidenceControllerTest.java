package vn.unit.affordability.dossier.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import vn.unit.affordability.dossier.dto.CreateEvidenceRequest;
import vn.unit.affordability.dossier.dto.EvidenceOcrResultResponse;
import vn.unit.affordability.dossier.dto.EvidenceRecordResponse;
import vn.unit.affordability.dossier.dto.SubmitOcrResultRequest;
import vn.unit.affordability.dossier.service.EvidenceService;
import vn.unit.affordability.shared.exception.GlobalExceptionHandler;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@ExtendWith(MockitoExtension.class)
class EvidenceControllerTest {

    @Mock
    private EvidenceService evidenceService;

    private MockMvc mockMvc;

    private ObjectMapper objectMapper;

    private static final String VALID_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    @BeforeEach
    void setUp() {
        objectMapper = new ObjectMapper();
        mockMvc = MockMvcBuilders.standaloneSetup(new EvidenceController(evidenceService))
                .setControllerAdvice(new GlobalExceptionHandler())
                .build();
    }

    @Test
    @DisplayName("POST /api/v1/dossiers/{dossierId}/evidences returns 201 Created")
    void shouldRegisterEvidence() throws Exception {
        CreateEvidenceRequest request = CreateEvidenceRequest.builder()
                .fileName("sao_ke_vcb.pdf")
                .fileHash(VALID_HASH)
                .fileType("BANK_STATEMENT")
                .storagePath("/storage/dossier-1/sao_ke_vcb.pdf")
                .uploadedBy("maker_01")
                .fileSizeBytes(204800L)
                .mimeType("application/pdf")
                .build();

        EvidenceRecordResponse response = EvidenceRecordResponse.builder()
                .id("ev-1")
                .dossierId("dossier-1")
                .fileName("sao_ke_vcb.pdf")
                .fileHash(VALID_HASH)
                .fileType("BANK_STATEMENT")
                .status("RECEIVED")
                .ocrStatus("PENDING")
                .version(1)
                .isLatest(true)
                .build();

        when(evidenceService.registerEvidence(eq("dossier-1"), any(CreateEvidenceRequest.class)))
                .thenReturn(response);

        mockMvc.perform(post("/api/v1/dossiers/dossier-1/evidences")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("ev-1"))
                .andExpect(jsonPath("$.data.version").value(1))
                .andExpect(jsonPath("$.data.isLatest").value(true));
    }

    @Test
    @DisplayName("POST /api/v1/dossiers/{dossierId}/evidences returns 400 when SHA-256 hash is invalid")
    void shouldReturn400WhenFileHashInvalid() throws Exception {
        CreateEvidenceRequest request = CreateEvidenceRequest.builder()
                .fileName("sao_ke_vcb.pdf")
                .fileHash("invalid-short-hash")
                .fileType("BANK_STATEMENT")
                .storagePath("/storage/sao_ke.pdf")
                .uploadedBy("maker_01")
                .fileSizeBytes(204800L)
                .mimeType("application/pdf")
                .build();

        mockMvc.perform(post("/api/v1/dossiers/dossier-1/evidences")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isBadRequest())
                .andExpect(jsonPath("$.success").value(false))
                .andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
                .andExpect(jsonPath("$.data.fileHash").exists());
    }

    @Test
    @DisplayName("GET /api/v1/dossiers/{dossierId}/evidences?latestOnly=true returns filtered list")
    void shouldGetLatestEvidences() throws Exception {
        EvidenceRecordResponse item = EvidenceRecordResponse.builder()
                .id("ev-2")
                .dossierId("dossier-1")
                .fileName("sao_ke_v2.pdf")
                .version(2)
                .isLatest(true)
                .build();

        when(evidenceService.getEvidencesByDossierId("dossier-1", true))
                .thenReturn(List.of(item));

        mockMvc.perform(get("/api/v1/dossiers/dossier-1/evidences")
                        .param("latestOnly", "true")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data[0].id").value("ev-2"))
                .andExpect(jsonPath("$.data[0].version").value(2));
    }

    @Test
    @DisplayName("POST /api/v1/evidences/{evidenceId}/ocr-results returns 201 Created")
    void shouldSubmitOcrResult() throws Exception {
        SubmitOcrResultRequest request = SubmitOcrResultRequest.builder()
                .engineName("pdfplumber")
                .engineVersion("0.11.0")
                .confidenceScore(new BigDecimal("96.80"))
                .rawPayload("{\"pages\": 6}")
                .status("COMPLETED")
                .processedBy("ai-worker-01")
                .build();

        EvidenceOcrResultResponse response = EvidenceOcrResultResponse.builder()
                .id("ocr-1")
                .evidenceId("ev-1")
                .dossierId("dossier-1")
                .ocrVersion(1)
                .engineName("pdfplumber")
                .status("COMPLETED")
                .processedAt(OffsetDateTime.now())
                .build();

        when(evidenceService.submitOcrResult(eq("ev-1"), any(SubmitOcrResultRequest.class)))
                .thenReturn(response);

        mockMvc.perform(post("/api/v1/evidences/ev-1/ocr-results")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(objectMapper.writeValueAsString(request)))
                .andExpect(status().isCreated())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.ocrVersion").value(1))
                .andExpect(jsonPath("$.data.status").value("COMPLETED"));
    }

    @Test
    @DisplayName("GET /api/v1/evidences/{evidenceId}/ocr-results/latest returns latest OCR result")
    void shouldGetLatestOcrResult() throws Exception {
        EvidenceOcrResultResponse response = EvidenceOcrResultResponse.builder()
                .id("ocr-2")
                .evidenceId("ev-1")
                .ocrVersion(2)
                .engineName("pdfplumber")
                .status("COMPLETED")
                .build();

        when(evidenceService.getLatestOcrResult("ev-1")).thenReturn(response);

        mockMvc.perform(get("/api/v1/evidences/ev-1/ocr-results/latest")
                        .accept(MediaType.APPLICATION_JSON))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$.success").value(true))
                .andExpect(jsonPath("$.data.id").value("ocr-2"))
                .andExpect(jsonPath("$.data.ocrVersion").value(2));
    }
}
