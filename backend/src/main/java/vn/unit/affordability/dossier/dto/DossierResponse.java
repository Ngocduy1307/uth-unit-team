package vn.unit.affordability.dossier.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

@Getter
@Setter
@NoArgsConstructor
@AllArgsConstructor
@Builder
@JsonInclude(JsonInclude.Include.NON_NULL)
public class DossierResponse {

    private String id;
    private String applicationId;
    private String applicantId;
    private String applicantName;
    private String bankCode;
    private String status;
    private String makerId;
    private String checkerId;
    private LocalDate analysisDate;
    private String loanProduct;
    private BigDecimal requestedAmount;
    private Integer requestedTenorMonths;
    private BigDecimal proposedInterestRate;
    private BigDecimal monthlyDeclaredLivingExpense;
    private OffsetDateTime createdAt;
    private OffsetDateTime updatedAt;
}
