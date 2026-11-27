package vn.unit.affordability.dossier.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.DisplayName;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import vn.unit.affordability.dossier.dto.CreateEvidenceRequest;
import vn.unit.affordability.dossier.dto.EvidenceOcrResultResponse;
import vn.unit.affordability.dossier.dto.EvidenceRecordResponse;
import vn.unit.affordability.dossier.dto.SubmitOcrResultRequest;
import vn.unit.affordability.dossier.model.EvidenceOcrResult;
import vn.unit.affordability.dossier.model.EvidenceRecord;
import vn.unit.affordability.dossier.repository.DossierRepository;
import vn.unit.affordability.dossier.repository.EvidenceOcrResultRepository;
import vn.unit.affordability.dossier.repository.EvidenceRecordRepository;
import vn.unit.affordability.dossier.service.impl.EvidenceServiceImpl;
import vn.unit.affordability.shared.audit.model.AuditLog;
import vn.unit.affordability.shared.audit.repository.AuditLogRepository;
import vn.unit.affordability.shared.exception.BusinessValidationException;
import vn.unit.affordability.shared.exception.ResourceNotFoundException;
import vn.unit.affordability.shared.outbox.model.OutboxEvent;
import vn.unit.affordability.shared.outbox.repository.OutboxEventRepository;

import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class EvidenceServiceTest {

    @Mock
    private EvidenceRecordRepository evidenceRecordRepository;

    @Mock
    private EvidenceOcrResultRepository ocrResultRepository;

    @Mock
    private DossierRepository dossierRepository;

    @Mock
    private AuditLogRepository auditLogRepository;

    @Mock
    private OutboxEventRepository outboxEventRepository;

    private EvidenceServiceImpl evidenceService;

    private static final String VALID_HASH = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";

    @BeforeEach
    void setUp() {
        evidenceService = new EvidenceServiceImpl(
                evidenceRecordRepository,
                ocrResultRepository,
                dossierRepository,
                auditLogRepository,
                outboxEventRepository,
                new ObjectMapper()
        );
    }

    @Test
    @DisplayName("Should register evidence v1 with audit log and outbox event")
    void shouldRegisterFirstEvidenceVersion() {
        CreateEvidenceRequest request = CreateEvidenceRequest.builder()
                .fileName("sao_ke_vcb.pdf")
                .fileHash(VALID_HASH)
                .fileType("BANK_STATEMENT")
                .storagePath("/storage/dossier-1/sao_ke_vcb.pdf")
                .uploadedBy("maker_01")
                .fileSizeBytes(204800L)
                .mimeType("application/pdf")
                .build();

        when(dossierRepository.existsById("dossier-1")).thenReturn(true);
        when(evidenceRecordRepository.findByDossierIdAndFileHash("dossier-1", VALID_HASH))
                .thenReturn(Optional.empty());
        when(evidenceRecordRepository.findByDossierIdAndFileTypeOrderByVersionDesc("dossier-1", "BANK_STATEMENT"))
                .thenReturn(List.of());
        when(evidenceRecordRepository.save(any(EvidenceRecord.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        EvidenceRecordResponse response = evidenceService.registerEvidence("dossier-1", request);

        assertEquals(1, response.getVersion());
        assertTrue(response.getIsLatest());
        assertEquals("RECEIVED", response.getStatus());
        assertEquals("PENDING", response.getOcrStatus());

        ArgumentCaptor<AuditLog> auditCaptor = ArgumentCaptor.forClass(AuditLog.class);
        verify(auditLogRepository).save(auditCaptor.capture());
        assertEquals("EVIDENCE", auditCaptor.getValue().getEntityName());
        assertEquals("CREATE", auditCaptor.getValue().getAction());

        ArgumentCaptor<OutboxEvent> outboxCaptor = ArgumentCaptor.forClass(OutboxEvent.class);
        verify(outboxEventRepository).save(outboxCaptor.capture());
        assertEquals("EVIDENCE_RECEIVED", outboxCaptor.getValue().getEventType());
    }

    @Test
    @DisplayName("Should increment version and mark previous evidence as not latest")
    void shouldIncrementEvidenceVersionAndRetirePrevious() {
        EvidenceRecord previous = EvidenceRecord.builder()
                .id("ev-1")
                .dossierId("dossier-1")
                .fileName("sao_ke_v1.pdf")
                .fileHash("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")
                .fileType("BANK_STATEMENT")
                .version(1)
                .isLatest(true)
                .build();

        CreateEvidenceRequest request = CreateEvidenceRequest.builder()
                .fileName("sao_ke_v2.pdf")
                .fileHash(VALID_HASH)
                .fileType("BANK_STATEMENT")
                .storagePath("/storage/dossier-1/sao_ke_v2.pdf")
                .uploadedBy("maker_02")
                .fileSizeBytes(304800L)
                .mimeType("application/pdf")
                .reason("Bo sung trang con thieu")
                .build();

        when(dossierRepository.existsById("dossier-1")).thenReturn(true);
        when(evidenceRecordRepository.findByDossierIdAndFileHash("dossier-1", VALID_HASH))
                .thenReturn(Optional.empty());
        when(evidenceRecordRepository.findByDossierIdAndFileTypeOrderByVersionDesc("dossier-1", "BANK_STATEMENT"))
                .thenReturn(List.of(previous));
        when(evidenceRecordRepository.save(any(EvidenceRecord.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        EvidenceRecordResponse response = evidenceService.registerEvidence("dossier-1", request);

        assertEquals(2, response.getVersion());
        assertTrue(response.getIsLatest());
        assertFalse(previous.getIsLatest());
        assertEquals("maker_02", previous.getUpdatedBy());
    }

    @Test
    @DisplayName("Should reject duplicate SHA-256 hash within same dossier")
    void shouldRejectDuplicateFileHash() {
        CreateEvidenceRequest request = CreateEvidenceRequest.builder()
                .fileName("sao_ke.pdf")
                .fileHash(VALID_HASH)
                .fileType("BANK_STATEMENT")
                .storagePath("/storage/sao_ke.pdf")
                .uploadedBy("maker_01")
                .fileSizeBytes(1024L)
                .mimeType("application/pdf")
                .build();

        when(dossierRepository.existsById("dossier-1")).thenReturn(true);
        when(evidenceRecordRepository.findByDossierIdAndFileHash("dossier-1", VALID_HASH))
                .thenReturn(Optional.of(EvidenceRecord.builder().id("ev-existing").build()));

        assertThrows(BusinessValidationException.class,
                () -> evidenceService.registerEvidence("dossier-1", request));
    }

    @Test
    @DisplayName("Should save OCR result with auto-incremented version and update evidence status")
    void shouldSubmitOcrResultAndIncrementVersion() {
        EvidenceRecord evidence = EvidenceRecord.builder()
                .id("ev-1")
                .dossierId("dossier-1")
                .ocrStatus("PENDING")
                .status("RECEIVED")
                .build();

        EvidenceOcrResult previousOcr = EvidenceOcrResult.builder()
                .id("ocr-1")
                .evidenceId("ev-1")
                .ocrVersion(1)
                .build();

        SubmitOcrResultRequest request = SubmitOcrResultRequest.builder()
                .engineName("pdfplumber")
                .engineVersion("0.11.0")
                .confidenceScore(new BigDecimal("97.50"))
                .rawPayload("{\"pages\": 6, \"rows\": 120}")
                .extractedSummary("{\"accountNumber\": \"0071000123456\"}")
                .status("COMPLETED")
                .processedBy("ai-service-worker")
                .build();

        when(evidenceRecordRepository.findById("ev-1")).thenReturn(Optional.of(evidence));
        when(ocrResultRepository.findFirstByEvidenceIdOrderByOcrVersionDesc("ev-1"))
                .thenReturn(Optional.of(previousOcr));
        when(ocrResultRepository.save(any(EvidenceOcrResult.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));
        when(evidenceRecordRepository.save(any(EvidenceRecord.class)))
                .thenAnswer(invocation -> invocation.getArgument(0));

        EvidenceOcrResultResponse response = evidenceService.submitOcrResult("ev-1", request);

        assertEquals(2, response.getOcrVersion());
        assertEquals("COMPLETED", response.getStatus());
        assertEquals("EXTRACTED", evidence.getStatus());
        assertEquals("COMPLETED", evidence.getOcrStatus());
        assertNotNull(evidence.getOcrProcessedAt());
        verify(auditLogRepository).save(any(AuditLog.class));
        verify(outboxEventRepository).save(any(OutboxEvent.class));
    }

    @Test
    @DisplayName("Should throw BusinessValidationException when rawPayload is invalid JSON")
    void shouldRejectInvalidJsonPayload() {
        EvidenceRecord evidence = EvidenceRecord.builder()
                .id("ev-1")
                .dossierId("dossier-1")
                .build();

        SubmitOcrResultRequest request = SubmitOcrResultRequest.builder()
                .engineName("pdfplumber")
                .rawPayload("{invalid-json")
                .status("COMPLETED")
                .processedBy("ai-worker")
                .build();

        when(evidenceRecordRepository.findById("ev-1")).thenReturn(Optional.of(evidence));

        assertThrows(BusinessValidationException.class,
                () -> evidenceService.submitOcrResult("ev-1", request));
    }

    @Test
    @DisplayName("Should throw ResourceNotFoundException when evidence does not exist")
    void shouldThrowNotFoundForMissingEvidence() {
        when(evidenceRecordRepository.findById("missing-id")).thenReturn(Optional.empty());

        assertThrows(ResourceNotFoundException.class,
                () -> evidenceService.getEvidenceById("missing-id"));
    }
}
